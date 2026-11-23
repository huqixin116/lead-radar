# -*- coding: utf-8 -*-
"""采集入口（小批量）。
用法：
  python -m collector.run --platform douyin --keyword 示例关键词1
  python -m collector.run --all   # 按 config.yaml 里的平台和关键词各跑一轮
不登录不抓：缺登录态会提示先跑 login，不会绕验证。
风控触发或连续失败 3 次时立刻停止整轮，不继续下一个关键词/平台。
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("lead-radar")

COLLECTORS = {
    "douyin": "collector.douyin.DouyinCollector",
    "xiaohongshu": "collector.xiaohongshu.XiaohongshuCollector",
    "bilibili": "collector.bilibili.BilibiliCollector",
    "weibo": "collector.weibo.WeiboCollector",
    "tieba": "collector.tieba.TiebaCollector",
}


def _load_collector(name: str):
    mod_name, cls_name = COLLECTORS[name].rsplit(".", 1)
    import importlib
    return getattr(importlib.import_module(mod_name), cls_name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", choices=list(COLLECTORS))
    ap.add_argument("--keyword", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    sys.path.insert(0, root)
    from collector.config import load_config, resolve_db_path
    from storage.db import init_db, create_queue_from_comments
    from scoring.scorer import make_draft
    from tools.risk import RiskDetected

    cfg = load_config(os.path.join(root, args.config) if not os.path.isabs(args.config) else args.config)
    db_path = resolve_db_path(cfg, root)
    conn = init_db(db_path)

    if args.all:
        platforms = cfg.get("platforms", ["douyin"])
        keywords = cfg.get("keywords", [])
    else:
        platforms = [args.platform or cfg.get("platforms", ["douyin"])[0]]
        keywords = [args.keyword] if args.keyword else cfg.get("keywords", [])[:1]
    if not keywords:
        print("config.yaml 里 keywords 为空，请先填 1 个关键词再跑。")
        return 2

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("未装 playwright，请先：pip install -r requirements.txt && playwright install chromium")
        return 2

    from collector.base import launch_browser_with_cdp, close_browser

    headless = bool(cfg.get("browser", {}).get("headless", False))
    # run() 里 headless 已由 launch 函数按配置处理，这里保留参数兼容旧调用
    _ = headless
    stopped_risk = False
    for platform in platforms:
        if stopped_risk:
            break
        cls = _load_collector(platform)
        collector = cls(cfg, conn, headless=headless)
        if not collector.require_login():
            print(f"[{platform}] 跳过：先跑 python -m collector.login --platform {platform}")
            continue
        with sync_playwright() as p:
            browser, ctx = launch_browser_with_cdp(
                p, cfg, platform, storage_state=collector.auth_path)
            try:
                page = ctx.new_page()
                ok, reason = collector.pong(page)
                if not ok:
                    print(f"[{platform}] 登录健康检查失败：{reason}，停止。"
                          "请先跑 python -m collector.login --platform "
                          f"{platform} 重新扫码登录，不要绕验证码。")
                    stopped_risk = True
                    break
                logger.info("[%s] pong 通过：%s", platform, reason)
                for kw in keywords:
                    try:
                        _n, _m, stopped = collector.run_for_keyword(page, kw)
                    except RiskDetected as e:
                        print(f"[{platform}] RISK_DETECTED：{e.reason}，立刻停止整轮。")
                        logger.error("[%s] RISK_DETECTED：%s", platform, e.reason)
                        stopped_risk = True
                        break
                    if stopped:
                        print(f"[{platform}] 连续失败 3 次，熔断停止，不继续下一个关键词/平台。")
                        stopped_risk = True
                        break
            finally:
                close_browser(browser, ctx)

    if stopped_risk:
        print("已因风控/连续失败停止整轮。请检查日志、换住宅/手机 IP、"
              "等一段时间再小批量重试，不要立刻重跑。")
        return 1

    created = create_queue_from_comments(
        conn, min_score=2,
        draft_fn=lambda lead: make_draft(
            cfg.get("product_name", ""), cfg.get("product_intro", ""), lead))
    print(f"已把 {created} 条高意向评论放进待审队列（pending_review），请去看板人工审核，不要直接发。")
    print(f"数据库：{db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
