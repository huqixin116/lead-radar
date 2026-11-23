# -*- coding: utf-8 -*-
"""风控检测：只做关键词/状态码判断，检测到就停，不绕过。

一旦检测到验证码、滑块、登录过期、IP 被封、操作频繁，
调用方必须立刻停止整轮采集/发送，不要重试、不要换平台继续。
"""
from __future__ import annotations

# 状态码：这些一律不重试，直接停
BLOCK_STATUS_CODES = {401, 403, 429, 418, 503}

RISK_KEYWORDS = [
    # 验证码 / 滑块
    "验证码", "滑块", "滑动验证", "captcha", "slider", "verify you are human",
    "human verification", "请完成验证", "安全验证",
    # 登录过期
    "登录已过期", "登录过期", "请重新登录", "扫码登录", "请先登录",
    "login expired", "please log in", "session expired",
    # IP / 访问受限
    "IP 被封", "IP封禁", "访问受限", "访问过于频繁", "操作频繁",
    "操作过于频繁", "请求过于频繁", "too many requests", "access denied",
    "forbidden", "blocked", "你的网络存在异常", "异常访问",
    # 私信受限
    "私信受限", "发送失败", "消息发送失败", "已被限制", "账号异常",
    "account restricted", "暂时无法发送",
]

NORMAL_PHRASES = [
    "这条视频很有意思", "多少钱？哪里买？", "求链接，想入手一个",
    "这个好用吗？推荐吗", "你好，今天天气不错",
]


class RiskDetected(Exception):
    """风控触发：调用方应立刻停止整轮，不要重试。"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def detect_risk(text: str | None = None, status: int | None = None) -> tuple:
    """返回 (is_risk: bool, reason: str)。text 为页面文本或错误信息。"""
    if status is not None:
        try:
            code = int(status)
        except (TypeError, ValueError):
            code = None
        if code in BLOCK_STATUS_CODES:
            return True, f"HTTP {code}：疑似被限流/封禁，不重试"
    t = (text or "").strip()
    if not t:
        return False, ""
    low = t.lower()
    for kw in RISK_KEYWORDS:
        if kw.lower() in low:
            return True, f"命中风控关键词：{kw}"
    return False, ""
