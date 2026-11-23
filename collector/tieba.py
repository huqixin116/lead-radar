# -*- coding: utf-8 -*-
"""百度贴吧：关键词搜帖子 -> 抓回帖。"""
from __future__ import annotations

import logging

from .base import BaseCollector

logger = logging.getLogger("lead-radar")


class TiebaCollector(BaseCollector):
    platform = "tieba"
    home_url = "https://tieba.baidu.com/"
    search_url_template = "https://tieba.baidu.com/f/search/res?isnew=1&kw=&qw={keyword}"

    def collect_contents(self, page, keyword: str):
        items = []
        for a in page.query_selector_all("a[href*='/p/']"):
            try:
                href = a.get_attribute("href") or ""
                if "/p/" not in href:
                    continue
                url = href if href.startswith("http") else "https://tieba.baidu.com" + href
                cid = url.rstrip("/").split("/")[-1].split("?")[0]
                title = (a.inner_text() or "").strip().replace("\n", " ")[:80]
                if any(x["url"] == url for x in items):
                    continue
                items.append({"id": cid, "title": title or "贴吧帖子",
                              "url": url, "author": ""})
            except Exception as e:  # noqa: BLE001
                logger.debug("tieba content parse failed: %s", e)
        if not items:
            logger.warning("[tieba] 没找到帖子卡片，页面结构可能变了")
        return items

    def collect_comments(self, page, content: dict):
        out, seen = [], set()
        self.scroll_down(page, times=3, pause=1.2)
        # 选择器本身已是叶子 .l_post、正文已优先取 .d_post_content，
        # 不改；只加嵌套跳过和空白归一化去重（原来按原始文本去重，
        # 换行/空格不同会被当成两条）。
        for el in page.query_selector_all(".l_post, [class*='l_post']"):
            if self.has_nested_comment(el, (".l_post", "[class*='l_post']")):
                continue
            try:
                # 回帖正文优先取 .d_post_content
                body = el.query_selector(".d_post_content")
                text = self.normalize_text(
                    body.inner_text() if body else el.inner_text() or "")
            except Exception:
                continue
            if len(text) < 2 or len(text) > 500 or text in seen:
                continue
            seen.add(text)
            nickname, user_id, homepage = "", "", ""
            try:
                link = el.query_selector("a[href*='/home/main']")
                if link:
                    homepage = link.get_attribute("href") or ""
                    if homepage and not homepage.startswith("http"):
                        homepage = "https://tieba.baidu.com" + homepage
                    nickname = (link.inner_text() or "").strip()
            except Exception:
                pass
            out.append({"nickname": nickname, "user_id": user_id,
                        "homepage_url": homepage, "text": text,
                        "created_at": "", "likes": 0, "reply_to": ""})
            if len(out) >= 50:
                break
        if not out:
            logger.warning("[tieba] 回帖为空或选择器失效：%s", content.get("url"))
        return out
