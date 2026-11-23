# -*- coding: utf-8 -*-
"""B站：关键词搜视频 -> 抓评论。"""
from __future__ import annotations

import logging

from .base import BaseCollector

logger = logging.getLogger("lead-radar")


class BilibiliCollector(BaseCollector):
    platform = "bilibili"
    home_url = "https://www.bilibili.com/"
    search_url_template = "https://search.bilibili.com/all?keyword={keyword}"

    def collect_contents(self, page, keyword: str):
        items = []
        for a in page.query_selector_all("a[href*='/video/BV']"):
            try:
                href = a.get_attribute("href") or ""
                if "/video/BV" not in href:
                    continue
                url = href if href.startswith("http") else "https:" + href
                cid = url.rstrip("/").split("/")[-1].split("?")[0]
                title = (a.get_attribute("title") or a.inner_text() or "").strip()[:80]
                if any(x["url"] == url for x in items):
                    continue
                items.append({"id": cid, "title": title or "B站视频",
                              "url": url, "author": ""})
            except Exception as e:  # noqa: BLE001
                logger.debug("bilibili content parse failed: %s", e)
        if not items:
            logger.warning("[bilibili] 没找到视频卡片，页面结构可能变了")
        return items

    def collect_comments(self, page, content: dict):
        out, seen = [], set()
        self.scroll_down(page, times=4, pause=1.2)
        # 选择器本身已是叶子 .reply-item，不改；只加嵌套跳过
        # （子回复里也含 .reply-item）和正文优先取子节点、归一化去重。
        for el in page.query_selector_all(".reply-item, [class*='reply-item']"):
            if self.has_nested_comment(
                    el, (".reply-item", "[class*='reply-item']")):
                continue
            text = self.comment_body(el)
            if len(text) < 2 or len(text) > 500 or text in seen:
                continue
            seen.add(text)
            nickname, user_id, homepage = "", "", ""
            try:
                link = el.query_selector("a[href*='space.bilibili.com']")
                if link:
                    homepage = link.get_attribute("href") or ""
                    user_id = homepage.rstrip("/").split("/")[-1]
                    nickname = (link.inner_text() or "").strip()
            except Exception:
                pass
            out.append({"nickname": nickname, "user_id": user_id,
                        "homepage_url": homepage, "text": text,
                        "created_at": "", "likes": 0, "reply_to": ""})
            if len(out) >= 50:
                break
        if not out:
            logger.warning("[bilibili] 评论为空或选择器失效：%s", content.get("url"))
        return out
