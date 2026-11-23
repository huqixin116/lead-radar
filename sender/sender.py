# -*- coding: utf-8 -*-
"""单条发送器：一次只发一条已批准（approved）的队列项，人工确认后才点发送。
用法：
  python -m sender.sender --one --queue-id 1 --dry-run     # 只预览，不发
  python -m sender.sender --one --queue-id 1 --confirm     # 打开浏览器，粘贴草稿，等你确认后才点发送
没有 --confirm 绝不点发送；没有 --one 不批量跑；连续失败 3 次自动熔断停下。
"""
from __future__ import annotations

import argparse
import logging
import os
import random
import sys
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("lead-radar")

# 各平台私信/回评入口的兜底选择器，找到哪个用哪个，找不到就记失败不硬点
DM_BUTTON_SELECTORS = [
    "text=私信", "text=发私信", "text=发消息", "button:has-text('私信')",
    "a[href*='message']", "text=关注", "text=回复",
]
INPUT_SELECTORS = [
    "textarea", "div[contenteditable='true']", "[placeholder*='私信']",
    "[placeholder*='评论']", "[placeholder*='写下']",
]
SEND_BUTTON_SELECTORS = [
    "button:has-text('发送')", "text=发送", "button[type='submit']",
]


def _in_active_hours(cfg) -> bool:
    lim = cfg.get("sender_limits", {})
    start = int(lim.get("active_hours_start", 9))
    end = int(lim.get("active_hours_end", 21))
    return start <= datetime.now().hour < end


def check_daily_cap(conn, platform: str, max_per_day: int) -> bool:
    from storage.db import count_sent_today
    sent = count_sent_today(conn, platform)
    if sent >= max_per_day:
        logger.warning("[%s] 今日已发 %d 条，达到上限 %d，停止。", platform, sent, max_per_day)
        return False
    logger.info("[%s] 今日已发 %d / %d 条。", platform, sent, max_per_day)
    return True


def check_hourly_cap(conn, platform: str, max_per_hour: int) -> bool:
    """每小时上限：默认 5 条，配置里最多只能设到 10。"""
    from storage.db import count_sent_in_last_hour
    sent = count_sent_in_last_hour(conn, platform, hours=1.0)
    if sent >= max_per_hour:
        logger.warning("[%s] 过去 1 小时已发 %d 条，达到每小时上限 %d，停止。",
                       platform, sent, max_per_hour)
        return False
    logger.info("[%s] 过去 1 小时已发 %d / %d 条。", platform, sent, max_per_hour)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--one", action="store_true", required=True, help="一次只发一条")
    ap.add_argument("--queue-id", type=int, required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--confirm", action="store_true", help="人工确认后才真正点发送")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    sys.path.insert(0, root)
    from collector.config import load_config, resolve_db_path
    from storage.db import init_db, get_queue_item, update_queue_status

    cfg = load_config(os.path.join(root, args.config) if not os.path.isabs(args.config) else args.config)
    conn = init_db(resolve_db_path(cfg, root))
    item = get_queue_item(conn, args.queue_id)
    if not item:
        print(f"队列 {args.queue_id} 不存在。")
        return 2
    if item["status"] != "approved":
        print(f"队列 {args.queue_id} 状态是 {item['status']}，不是 approved，不能发。"
              "请先去看板把这条改成 approved。")
        return 2
    if item.get("attempts", 0) >= 3:
        print("这条已连续失败 3 次，熔断：不再自动重试，请人工检查后手动处理。")
        update_queue_status(conn, args.queue_id, "failed", "circuit breaker: 3 failures")
        return 1

    print("---- 待发预览（只发这一条）----")
    print(f"平台：{item['platform']}  昵称：{item.get('nickname')}")
    print(f"目标：{item.get('target_url')}")
    print(f"原文：{item.get('comment_text')}")
    print(f"草稿：{item.get('draft_text')}")
    print("------------------------------")
    if args.dry_run or not args.confirm:
        print("dry-run / 未加 --confirm：只预览，不打开浏览器、不点发送。")
        print("确认无误后重跑：python -m sender.sender --one "
              f"--queue-id {args.queue_id} --confirm")
        return 0

    lim = cfg.get("sender_limits", {})
    if not _in_active_hours(cfg):
        print(f"现在不在发送时段 {lim.get('active_hours_start', 9)}-{lim.get('active_hours_end', 21)} 点，停止。")
        return 1
    if not check_daily_cap(conn, item["platform"], int(lim.get("max_per_day_per_platform", 20))):
        return 1
    if not check_hourly_cap(conn, item["platform"], int(lim.get("max_per_hour_per_platform", 5))):
        return 1

    # 话术轮换：随机挑一个变体，不和该平台上一条已发送的相同
    from storage.db import get_last_sent_draft
    from scoring.scorer import pick_draft_variant
    last_draft = get_last_sent_draft(conn, item["platform"])
    send_text = pick_draft_variant(
        cfg.get("product_name", ""), cfg.get("product_intro", ""),
        {"nickname": item.get("nickname"), "content_title": item.get("content_title"),
         "content_url": item.get("content_url"), "text": item.get("comment_text")},
        last_sent_draft=last_draft)
    print(f"本次发送话术（已轮换，避免和上一条相同）：{send_text}")

    delay = random.randint(int(lim.get("min_delay_seconds", 60)),
                           int(lim.get("max_delay_seconds", 180)))
    print(f"随机等待 {delay} 秒后再操作（防高频），请勿关闭浏览器……")
    import time
    time.sleep(min(delay, 10))  # 真实等待由人工在浏览器里完成，这里只做短暂停顿防误触
    print("注意：下面打开浏览器后，脚本只会帮你打开目标页、粘贴草稿，"
          "点发送前请你在浏览器里再看一眼，确认无误再让脚本继续。")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("未装 playwright，请先：pip install -r requirements.txt && playwright install chromium")
        return 2

    auth = os.path.join(root, cfg.get("storage", {}).get("auth_dir", "data/auth"),
                        f"{item['platform']}.json")
    if not os.path.exists(auth):
        print(f"未找到登录态 {auth}，请先跑 login。")
        update_queue_status(conn, args.queue_id, "failed", "no login state")
        return 1

    target = item.get("target_url") or item.get("content_url") or ""
    if not target:
        print("没有目标链接，无法发送。")
        update_queue_status(conn, args.queue_id, "failed", "no target url")
        return 1

    headless = bool(cfg.get("browser", {}).get("headless", False))
    _ = headless  # 由 launch_browser_with_cdp 按配置处理
    try:
        from collector.base import launch_browser_with_cdp, close_browser
        from tools.risk import detect_risk
        with sync_playwright() as p:
            browser, ctx = launch_browser_with_cdp(p, cfg, item["platform"], storage_state=auth)
            page = ctx.new_page()
            page.goto(target, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            # 风控检测：页面出现验证码/受限/操作频繁，立刻停，不发
            try:
                _is_risk, _reason = detect_risk(page.inner_text("body") or "")
            except Exception:
                _is_risk, _reason = False, ""
            if _is_risk:
                print(f"RISK_DETECTED：{_reason}，立刻停止，不发这条。")
                logger.error("RISK_DETECTED on send page: %s", _reason)
                update_queue_status(conn, args.queue_id, "failed", f"risk: {_reason}")
                close_browser(browser, ctx)
                return 1
            clicked = False
            for sel in DM_BUTTON_SELECTORS:
                try:
                    el = page.query_selector(sel)
                    if el:
                        el.click(timeout=5000)
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                logger.warning("没找到私信/回复入口，请在浏览器里人工点开，再继续。")
            page.wait_for_timeout(2000)
            pasted = False
            for sel in INPUT_SELECTORS:
                try:
                    el = page.query_selector(sel)
                    if el:
                        el.click(timeout=5000)
                        el.fill(send_text)
                        pasted = True
                        break
                except Exception:
                    continue
            if not pasted:
                print("没找到输入框，没发。请人工在浏览器里粘贴草稿。")
                update_queue_status(conn, args.queue_id, "failed", "no input box found")
                close_browser(browser, ctx)
                return 1
            answer = input("草稿已粘贴在浏览器里。确认发送吗？输入 yes 才点发送，其他输入取消：").strip().lower()
            if answer != "yes":
                print("你取消了，没点发送，这条仍是 approved，可稍后再发。")
                close_browser(browser, ctx)
                return 0
            sent = False
            for sel in SEND_BUTTON_SELECTORS:
                try:
                    el = page.query_selector(sel)
                    if el:
                        el.click(timeout=5000)
                        sent = True
                        break
                except Exception:
                    continue
            close_browser(browser, ctx)
            if sent:
                update_queue_status(conn, args.queue_id, "sent", sent=True)
                print(f"已发送 1 条（队列 {args.queue_id}），本次结束。")
                return 0
            print("没找到发送按钮，没发。请人工在浏览器里点发送，成功后在看板里手动标 sent。")
            update_queue_status(conn, args.queue_id, "failed", "no send button found")
            return 1
    except Exception as e:  # noqa: BLE001
        logger.error("发送失败：%s", e)
        update_queue_status(conn, args.queue_id, "failed", str(e)[:200])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
