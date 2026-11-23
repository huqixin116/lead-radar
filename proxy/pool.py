# -*- coding: utf-8 -*-
"""代理池接入点：只支持静态代理，不内置任何付费代理商。

设计：
- 配置里只填一个 static_proxy_url（例如 http://user:pass@host:port），
  开启后每次建浏览器上下文都走这个代理。
- 每个代理条目带 expires_at，过期后 get_or_refresh() 会重新加载。
- validate() 只做一次轻量 GET 到公开 echo 地址，超时 5 秒、重试 3 次，
  失败就把该代理标为不可用，不会无限重试。
- 默认关闭：enable_ip_proxy=false 时直接走本机 IP，看板会显示风险横幅，
  提醒用住宅/手机流量，不要用共享 VPN/服务器 IP。
"""
from __future__ import annotations

import logging
import random
import time
import urllib.request

logger = logging.getLogger("lead-radar")

# 轻量验证地址：只用来确认代理能通，不传任何业务数据
VALIDATE_URL = "https://httpbin.org/ip"


class StaticProxyProvider:
    """静态代理：配置里给什么就用什么，不做动态拉取。"""

    name = "static"

    def __init__(self, static_proxy_url: str = ""):
        self.static_proxy_url = (static_proxy_url or "").strip()

    def load(self) -> list:
        if not self.static_proxy_url:
            return []
        return [self.static_proxy_url]


class ProxyPool:
    """很小的代理池：随机取、过期刷新、失败标记。"""

    def __init__(self, proxies=None, expiry_seconds: int = 3600,
                 rng: random.Random | None = None):
        self.rng = rng or random
        self.expiry_seconds = int(expiry_seconds)
        self._entries = []  # list[dict{url, expires_at, bad}]
        for url in (proxies or []):
            if url:
                self.add(url)

    def add(self, url: str, expiry_seconds: int | None = None):
        ttl = int(expiry_seconds) if expiry_seconds is not None else self.expiry_seconds
        self._entries.append({
            "url": url, "expires_at": time.time() + ttl, "bad": False,
        })

    def is_expired(self, entry: dict, now: float | None = None) -> bool:
        return (now if now is not None else time.time()) >= entry["expires_at"]

    def get_proxy(self) -> str | None:
        """随机返回一个未过期、未标记坏的代理；没有返回 None。"""
        now = time.time()
        alive = [e for e in self._entries if not e["bad"] and not self.is_expired(e, now)]
        if not alive:
            return None
        return self.rng.choice(alive)["url"]

    def get_or_refresh(self, loader=None) -> str | None:
        """有可用代理直接返回；过期/没有时用 loader 重新加载一次再取。"""
        proxy = self.get_proxy()
        if proxy:
            return proxy
        if loader is not None:
            for url in loader():
                self.add(url)
            return self.get_proxy()
        return None

    def mark_bad(self, url: str):
        for e in self._entries:
            if e["url"] == url:
                e["bad"] = True

    def validate(self, url: str, timeout: float = 5.0, retries: int = 3,
                 opener=None) -> bool:
        """轻量验证：GET 公开 echo 地址，通了返回 True，否则 False。

        opener 可注入，测试里传假 opener 就不用联网。
        """
        last_err = None
        for _ in range(max(1, retries)):
            try:
                if opener is not None:
                    resp = opener(url)
                    status = getattr(resp, "status", 200)
                    if status == 200:
                        return True
                    last_err = f"status {status}"
                    continue
                req = urllib.request.Request(
                    VALIDATE_URL, headers={"User-Agent": "lead-radar/1.0"})
                proxy_handler = urllib.request.ProxyHandler(
                    {"http": url, "https": url})
                opener_obj = urllib.request.build_opener(proxy_handler)
                with opener_obj.open(req, timeout=timeout) as resp:
                    if resp.status == 200:
                        return True
                    last_err = f"status {resp.status}"
            except Exception as e:  # noqa: BLE001 - 验证失败就是不可用
                last_err = str(e)
        logger.warning("代理验证失败 %s：%s", url, last_err)
        return False


def get_playwright_proxy(config: dict) -> dict | None:
    """按配置返回 Playwright 的 proxy 参数，未开启返回 None。"""
    proxy_cfg = (config or {}).get("proxy", {}) or {}
    if not proxy_cfg.get("enable_ip_proxy"):
        return None
    url = (proxy_cfg.get("static_proxy_url") or "").strip()
    if not url:
        return None
    return {"server": url}


def proxy_disabled_warning(config: dict) -> str:
    proxy_cfg = (config or {}).get("proxy", {}) or {}
    if proxy_cfg.get("enable_ip_proxy") and proxy_cfg.get("static_proxy_url"):
        return ""
    return ("代理未开启：当前用直连 IP。请用住宅/手机流量，不要用共享 VPN/服务器 IP，"
            "否则同一个出口 IP 下多人操作很容易触发风控。")
