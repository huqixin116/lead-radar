# -*- coding: utf-8 -*-
"""人工登录：打开真实浏览器，让用户自己扫码登录，保存登录态。
用法：python -m collector.login --platform douyin
不识别、不绕过验证码；超时或失败就退出，让用户重试。
优先用 CDP 连本机真实 Chrome/Edge，连不上退回 Playwright 自带浏览器。
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("lead-radar")

HOMES = {
    "douyin": "https://www.douyin.com/",
    "xiaohongshu": "https://www.xiaohongshu.com/",
    "bilibili": "https://www.bilibili.com/",
    "weibo": "https://weibo.com/",
    "tieba": "https://tieba.baidu.com/",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", required=True, choices=list(HOMES))
    ap.add_argument("--timeout", type=int, default=300, help="等用户扫码的秒数，默认 300")
    args = ap.parse_args()

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    sys.path.insert(0, root)
    from collector.config import load_config
    from collector.base import launch_browser_with_cdp, close_browser
    cfg = load_config(os.path.join(root, "config.yaml"))
    auth_dir = os.path.join(root, cfg.get("storage", {}).get("auth_dir", "data/auth"))
    os.makedirs(auth_dir, exist_ok=True)
    out = os.path.join(auth_dir, f"{args.platform}.json")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("未装 playwright，请先：pip install -r requirements.txt && playwright install chromium")
        return 2

    print(f"正在打开浏览器，请在 {args.timeout} 秒内人工扫码登录 {args.platform}，不要让脚本代你过验证。")
    print(f"登录成功后登录态会保存到 {out}，下次采集复用。")
    with sync_playwright() as p:
        browser, ctx = launch_browser_with_cdp(p, cfg, args.platform)
        try:
            page = ctx.new_page()
            page.goto(HOMES[args.platform], wait_until="domcontentloaded")
            print("浏览器已打开，请扫码登录，登录完成后按回车保存（或等超时自动保存当前状态）...")
            try:
                input("登录完成后按回车：")
            except KeyboardInterrupt:
                print("已取消。")
                return 1
            ctx.storage_state(path=out)
        finally:
            close_browser(browser, ctx)
    print(f"已保存登录态到 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
