# -*- coding: utf-8 -*-
"""抖音：关键词搜视频 -> 抓评论。选择器以公开页面结构为起点，失效只记日志。"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

from .base import BaseCollector

logger = logging.getLogger("lead-radar")


class DouyinCollector(BaseCollector):
    platform = "douyin"
    home_url = "https://www.douyin.com/"
    search_url_template = "https://www.douyin.com/search/{keyword}"

    def collect_contents(self, page, keyword: str):
        items = []
        # 视频卡片：优先找 /video/ 链接，兜底找搜索结果里的链接
        for sel in ["a[href*='/video/']", "a[href*='/note/']"]:
            try:
                links = page.query_selector_all(sel)
            except Exception:
                continue
            for a in links:
                try:
                    href = a.get_attribute("href") or ""
                    if "/video/" not in href and "/note/" not in href:
                        continue
                    url = href if href.startswith("http") else "https://www.douyin.com" + href
                    cid = urlparse(url).path.strip("/").split("/")[-1]
                    title = (a.inner_text() or "").strip().replace("\n", " ")[:80]
                    if any(x["url"] == url for x in items):
                        continue
                    items.append({"id": cid, "title": title or "抖音视频",
                                  "url": url, "author": ""})
                except Exception as e:  # noqa: BLE001
                    logger.debug("douyin content parse failed: %s", e)
            if items:
                break
        if not items:
            logger.warning("[douyin] 没找到视频卡片，页面结构可能变了，先记日志不崩溃")
        return items

    def collect_comments(self, page, content: dict):
        out = []
        self.scroll_down(page, times=4, pause=1.2)
        # 只取叶子评论项，不取容器：以前用
        # "[data-e2e='comment-list'] div, .comment-item, [class*='comment']"
        # 会同时命中列表容器、评论项和里面的子 div，同一条评论抓多次，
        # 文本里还混着昵称+点赞+时间。现在只取 .comment-item 或
        # 列表的直接子元素，含嵌套评论项的容器直接跳过。
        containers = page.query_selector_all(
            ".comment-item, [data-e2e='comment-list'] > *"
        )
        seen = set()
        for el in containers:
            if self.has_nested_comment(
                    el, (".comment-item", "[data-e2e='comment-list']")):
                continue
            # 正文优先取子节点（.comment-text / .content / .text），
            # 取不到才回退到整块文本；空白折叠后按归一化文本去重。
            text = self.comment_body(el)
            if len(text) < 2 or len(text) > 500 or text in seen:
                continue
            seen.add(text)
            # 尽量取昵称/主页：找容器内的用户链接
            nickname, user_id, homepage = "", "", ""
            try:
                link = el.query_selector("a[href*='/user/']")
                if link:
                    homepage = link.get_attribute("href") or ""
                    if homepage and not homepage.startswith("http"):
                        homepage = "https://www.douyin.com" + homepage
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
            logger.warning("[douyin] 评论为空或选择器失效：%s", content.get("url"))
        return out
