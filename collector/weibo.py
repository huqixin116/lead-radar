# -*- coding: utf-8 -*-
"""微博：关键词搜帖子 -> 抓评论。"""
from __future__ import annotations

import logging

from .base import BaseCollector

logger = logging.getLogger("lead-radar")


class WeiboCollector(BaseCollector):
    platform = "weibo"
    home_url = "https://weibo.com/"
    search_url_template = "https://s.weibo.com/weibo?q={keyword}"

    def collect_contents(self, page, keyword: str):
        items = []
        for a in page.query_selector_all("a[href*='/detail/'], a[href*='weibo.com/']"):
            try:
                href = a.get_attribute("href") or ""
                if "weibo.com" not in href:
                    continue
                url = href if href.startswith("http") else "https:" + href
                cid = url.rstrip("/").split("/")[-1].split("?")[0]
                if any(x["url"] == url for x in items):
                    continue
                items.append({"id": cid, "title": (a.inner_text() or "").strip()[:80] or "微博帖子",
                              "url": url, "author": ""})
            except Exception as e:  # noqa: BLE001
                logger.debug("weibo content parse failed: %s", e)
        if not items:
            logger.warning("[weibo] 没找到帖子卡片，可能需先登录或页面结构变了")
        return items

    def collect_comments(self, page, content: dict):
        out, seen = [], set()
        self.scroll_down(page, times=3, pause=1.2)
        for el in page.query_selector_all("[class*='comment'], .list_li"):
            try:
                text = (el.inner_text() or "").strip()
            except Exception:
                continue
            if len(text) < 2 or len(text) > 500 or text in seen:
                continue
            seen.add(text)
            out.append({"nickname": "", "user_id": "", "homepage_url": "",
                        "text": text, "created_at": "", "likes": 0, "reply_to": ""})
            if len(out) >= 50:
                break
        if not out:
            logger.warning("[weibo] 评论为空或选择器失效：%s", content.get("url"))
        return out
