# -*- coding: utf-8 -*-
"""UA 轮换：自己维护的一小份桌面 Chrome UA 列表。

每次建浏览器上下文换一个真实桌面 UA，不要每次都用 Playwright 默认 UA。
但 UA 只是很小一环，单独换 UA 防不住风控，不要把它当成免封手段。
"""
from __future__ import annotations

import random

# 都是公开的、常见的桌面 Chrome UA 格式，自己按平台/版本手写，
# 不是从任何项目复制的列表。
DESKTOP_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


def get_all_uas() -> list:
    return list(DESKTOP_UAS)


def get_user_agent(rng: random.Random | None = None) -> str:
    """随机返回一个桌面 UA。传 rng 可在测试里固定种子。"""
    r = rng or random
    return r.choice(DESKTOP_UAS)
