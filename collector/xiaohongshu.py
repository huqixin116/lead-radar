# -*- coding: utf-8 -*-
"""小红书：关键词搜笔记 -> 抓评论。"""
from __future__ import annotations

import logging

from .base import BaseCollector

logger = logging.getLogger("lead-radar")


class XiaohongshuCollector(BaseCollector):
    platform = "xiaohongshu"
    home_url = "https://www.xiaohongshu.com/"
    search_url_template = (
        "https://www.xiaohongshu.com/search_result?keyword={keyword}"
        "&source=web_search_result_notes"
    )

    def collect_contents(self, page, keyword: str):
        items = []
        for sel in ["a[href*='/explore/']", "a[href*='/discovery/item/']"]:
            try:
                links = page.query_selector_all(sel)
            except Exception:
                continue
            for a in links:
                try:
                    href = a.get_attribute("href") or ""
                    if "/explore/" not in href and "/discovery/item/" not in href:
                        continue
                    url = href if href.startswith("http") else "https://www.xiaohongshu.com" + href
                    cid = url.rstrip("/").split("/")[-1].split("?")[0]
                    title = (a.inner_text() or "").strip().replace("\n", " ")[:80]
                    if any(x["url"] == url for x in items):
                        continue
                    items.append({"id": cid, "title": title or "小红书笔记",
                                  "url": url, "author": ""})
                except Exception as e:  # noqa: BLE001
                    logger.debug("xhs content parse failed: %s", e)
            if items:
                break
        if not items:
            logger.warning("[xiaohongshu] 没找到笔记卡片，页面结构可能变了")
        return items

    def collect_comments(self, page, content: dict):
        out, seen = [], set()
        self.scroll_down(page, times=4, pause=1.2)
        # 同抖音的修法：去掉宽泛的 [class*='comment']（会命中容器），
        # 只取叶子 .comment-item，跳过含嵌套评论项的容器，正文优先取子节点。
        for el in page.query_selector_all(".comment-item, [class*='comment-item']"):
            if self.has_nested_comment(
                    el, (".comment-item", "[class*='comment-item']")):
                continue
            text = self.comment_body(el)
            if len(text) < 2 or len(text) > 500 or text in seen:
                continue
            seen.add(text)
            nickname, user_id, homepage = "", "", ""
            try:
                link = el.query_selector("a[href*='/user/profile/']")
                if link:
                    homepage = link.get_attribute("href") or ""
                    if homepage and not homepage.startswith("http"):
                        homepage = "https://www.xiaohongshu.com" + homepage
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
            logger.warning("[xiaohongshu] 评论为空或选择器失效：%s", content.get("url"))
        return out
