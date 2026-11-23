# -*- coding: utf-8 -*-
"""读 config.yaml。PyYAML 有就用，没有就用最小解析（只读本项目固定字段）。"""
from __future__ import annotations

import os

DEFAULTS = {
    "product_name": "示例产品（请替换）",
    "product_intro": "示例介绍",
    "keywords": ["示例关键词1"],
    "platforms": ["douyin"],
    "per_platform": {"max_contents": 3, "max_comments_per_content": 20},
    "intent_keywords": {"buy": [], "negative": []},
    "sender_limits": {"max_per_day_per_platform": 20,
                      "max_per_hour_per_platform": 5,
                      "min_delay_seconds": 60, "max_delay_seconds": 180,
                      "active_hours_start": 9, "active_hours_end": 21},
    "storage": {"db_path": "data/leads.db", "export_dir": "data/exports",
                "auth_dir": "data/auth"},
    "browser": {"headless": False,
                "storage_state_template": "data/auth/{platform}.json",
                "cdp_mode": True,
                "custom_browser_path": "",
                "cdp_port": 9222,
                "connect_existing": True},
    "proxy": {"enable_ip_proxy": False, "provider": "static",
              "static_proxy_url": "", "pool_count": 2},
    "crawler": {"max_sleep_sec": 2, "jitter_sec": 3, "max_concurrency": 1},
}


def load_config(path: str = "config.yaml") -> dict:
    if not os.path.exists(path):
        return dict(DEFAULTS)
    try:
        import yaml  # type: ignore
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        cfg = dict(DEFAULTS)
        cfg.update(data)
        for k in ("per_platform", "intent_keywords", "sender_limits", "storage",
                  "browser", "proxy", "crawler"):
            if isinstance(data.get(k), dict):
                merged = dict(DEFAULTS[k])
                merged.update(data[k])
                cfg[k] = merged
        return cfg
    except Exception:
        return dict(DEFAULTS)


def resolve_db_path(config: dict, root: str) -> str:
    p = config.get("storage", {}).get("db_path", "data/leads.db")
    return p if os.path.isabs(p) else os.path.join(root, p)
