# -*- coding: utf-8 -*-
"""重试：只对瞬时错误重试，风控错误一律不重试。

瞬时错误：网络抖动、超时、连接重置。
不重试：401/403/429、验证码、滑块、登录过期、IP 被封、操作频繁。
"""
from __future__ import annotations

import logging
import time

from tools.risk import detect_risk

logger = logging.getLogger("lead-radar")

# 默认退避：第一次等 1 秒，第二次 2 秒，第三次 4 秒，最多 3 次尝试
DEFAULT_DELAYS = (1.0, 2.0, 4.0)
NON_RETRYABLE_CODES = {401, 403, 429, 418, 503}


def _status_of(exc: BaseException):
    for attr in ("status_code", "status", "code"):
        v = getattr(exc, attr, None)
        if isinstance(v, int):
            return v
    return None


def is_retryable_error(exc: BaseException) -> bool:
    """风控错误返回 False，其他错误返回 True。"""
    status = _status_of(exc)
    if status in NON_RETRYABLE_CODES:
        return False
    is_risk, _ = detect_risk(str(exc), status=status)
    return not is_risk


def call_with_retry(fn, max_attempts: int = 3, delays=DEFAULT_DELAYS,
                    sleep_fn=time.sleep):
    """调用 fn，最多 max_attempts 次。风控错误立即抛出，不重试。

    返回 fn 的返回值。最后一次失败仍抛出原异常。
    sleep_fn 可注入，测试里传空函数避免真等。
    """
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - 按类型决定是否重试
            last_exc = e
            if not is_retryable_error(e):
                logger.warning("不重试（风控/权限错误）：%s", e)
                raise
            if attempt >= max_attempts:
                raise
            delay = delays[attempt - 1] if attempt - 1 < len(delays) else delays[-1]
            logger.warning("第 %d 次失败，%s 秒后重试：%s", attempt, delay, e)
            sleep_fn(delay)
    raise last_exc  # pragma: no cover - 正常不会走到这里
