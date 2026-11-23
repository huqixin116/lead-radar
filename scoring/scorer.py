# -*- coding: utf-8 -*-
"""规则意向打分 0-4：只用关键词+规则，不调模型也能跑，离线可测。"""
from __future__ import annotations

import re

DEFAULT_BUY = ["多少钱", "多少米", "价格", "哪里买", "在哪买", "哪儿买",
               "求链接", "求购买", "怎么买", "如何购买", "想买", "入手",
               "下单", "推荐", "求推荐", "有货", "现货", "包邮"]
DEFAULT_NEGATIVE = ["广告", "骗子", "诈骗", "别买", "垃圾", "刷单",
                    "免费送", "抽奖", "加微信", "加我微信"]
PRICE_RE = re.compile(r"\d+(\.\d+)?\s*(元|块|¥|￥|rmb|RMB)")
QUESTION_WORDS = ["吗", "么", "怎么", "哪里", "哪儿", "如何", "能不能", "可以吗"]


def score_comment(text: str, buy_keywords=None, negative_keywords=None) -> int:
    """0=低，1=一般，2=关注，3=高意向，4=很高。"""
    t = (text or "").strip()
    if not t:
        return 0
    buy = buy_keywords if buy_keywords is not None else DEFAULT_BUY
    neg = negative_keywords if negative_keywords is not None else DEFAULT_NEGATIVE
    score = 0
    if any(k in t for k in buy):
        score += 2
    if "?" in t or "？" in t or any(w in t for w in QUESTION_WORDS):
        score += 1
    if PRICE_RE.search(t):
        score += 1
    if any(w in t for w in ("想要", "想买", "需要", "求")) and score < 4:
        # 避免重复加分：只有没命中购买词时才补 1 分
        if not any(k in t for k in buy):
            score += 1
    if any(k in t for k in neg):
        score -= 1
    if len(t) < 4:
        score -= 1
    return max(0, min(4, score))


def score_label(score: int) -> str:
    return {0: "低", 1: "一般", 2: "关注", 3: "高意向", 4: "很高"}.get(int(score), "低")


def make_draft(product_name: str, product_intro: str, lead: dict) -> str:
    """生成待审话术草稿：不放微信号/手机号/外链，合规留资靠平台官方组件。"""
    return make_draft_variants(product_name, product_intro, lead)[0]


def make_draft_variants(product_name: str, product_intro: str, lead: dict) -> list:
    """生成 3 个话术变体：开头、问法不同，意思相同。

    发送端随机挑一个，且不和该平台上一条已发送的草稿相同，
    避免短时间内连续发完全相同的文本被判营销。
    """
    nickname = lead.get("nickname") or "你好"
    title = lead.get("content_title") or lead.get("content_url") or ""
    comment = (lead.get("text") or lead.get("comment_text") or "")[:60]
    return [
        f"{nickname}你好，看到你在「{title}」下的评论：「{comment}」，"
        f"想问下你是对这类产品有需求吗？我是做{product_name}的，"
        f"{product_intro}。如果你方便，可以先说说你的预算和用途，我再帮你推荐，不方便也没关系，谢谢。",
        f"你好，我看到你刚才在「{title}」下留言：「{comment}」，"
        f"方便问一下你现在是在找这方面的产品吗？我是做{product_name}的，"
        f"{product_intro}。不着急，你先说说大概想要什么样的，我再看合不合适。",
        f"{nickname}，打扰了。看到你对「{title}」感兴趣，评论里说「{comment}」，"
        f"我这边是做{product_name}的，{product_intro}。"
        f"如果你还在选，可以告诉我你的预算和用途，我帮你看看，不合适也没关系。",
    ]


def pick_draft_variant(product_name: str, product_intro: str, lead: dict,
                       last_sent_draft: str = "") -> str:
    """随机挑一个变体，尽量不和上一条已发送的相同。"""
    import random
    variants = make_draft_variants(product_name, product_intro, lead)
    others = [v for v in variants if v != last_sent_draft]
    return random.choice(others) if others else variants[0]
