# -*- coding: utf-8 -*-
"""采集器基类：真实浏览器 + 人工登录态，不绕验证码，不调私有 API。

加固点（自己写的思路，不抄任何开源项目代码）：
- CDP 模式：先连用户本机真实 Chrome/Edge，连不上退回
  launch_persistent_context，每个平台独立 user_data_dir。
- 每次建上下文换一个桌面 UA，并注入自己写的最小 stealth 脚本
  （只藏 webdriver 标志、补 languages/plugins，不伪造指纹）。
- 登录健康检查 pong()：登录态缺失或页面出现风控词就停，不硬抓。
- 采集节奏全部带随机抖动，单并发；风控词一出现立刻停整轮。
"""
from __future__ import annotations

import logging
import os
import random
import time

logger = logging.getLogger("lead-radar")

# 自己写的最小 stealth 初始化脚本：只做两件最基础的事，
# 不复制任何开源项目的 stealth.min.js。
STEALTH_INIT_SCRIPT = """
() => {
  try {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
  } catch (e) {}
  try {
    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
  } catch (e) {}
  try {
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
  } catch (e) {}
}
"""


def get_jitter_delay(config: dict, rng: random.Random | None = None) -> float:
    """采集等待时间：基础 2 秒 + 随机 0-3 秒，默认返回 2-5 秒。

    配置在 crawler.max_sleep_sec / crawler.jitter_sec 里。
    """
    c = (config or {}).get("crawler", {}) or {}
    base = float(c.get("max_sleep_sec", 2))
    jitter = float(c.get("jitter_sec", 3))
    r = rng or random
    return base + r.uniform(0, jitter)


def jitter_sleep(config: dict, base_sec: float | None = None):
    """按抖动规则睡一会儿。base_sec 不给就用 get_jitter_delay()。"""
    if base_sec is None:
        delay = get_jitter_delay(config)
    else:
        c = (config or {}).get("crawler", {}) or {}
        delay = float(base_sec) + random.uniform(0, float(c.get("jitter_sec", 3)))
    time.sleep(max(0.0, delay))


def launch_browser_with_cdp(playwright, config: dict, platform: str,
                            storage_state: str | None = None):
    """打开浏览器，返回 (browser, context)。

    顺序：
    1. cdp_mode 开启且 connect_existing：先 try connect_over_cdp 连本机
       已打开的真实 Chrome/Edge（端口见 browser.cdp_port，默认 9222）。
    2. 连不上：退回 launch_persistent_context，每个平台独立
       user_data_dir（data/browser/<platform>），窗口 1920x1080。
    3. cdp_mode 关闭：直接走第 2 步。

    两种模式都走 UA 轮换、代理（如果开了）、stealth 初始化脚本。
    browser 为 None 时表示用的是 persistent context 自带的 browser，
    关闭时只关 context 即可，调用方用 close_browser() 统一处理。
    """
    from proxy.pool import get_playwright_proxy
    from tools.ua import get_user_agent

    browser_cfg = (config or {}).get("browser", {}) or {}
    headless = bool(browser_cfg.get("headless", False))
    cdp_mode = bool(browser_cfg.get("cdp_mode", True))
    cdp_port = int(browser_cfg.get("cdp_port", 9222))
    connect_existing = bool(browser_cfg.get("connect_existing", True))
    custom_path = (browser_cfg.get("custom_browser_path") or "").strip() or None
    proxy = get_playwright_proxy(config)
    ua = get_user_agent()
    logger.info("[%s] 本次 UA：%s", platform, ua)
    if proxy:
        logger.info("[%s] 走代理：%s", platform, proxy.get("server", ""))
    else:
        logger.warning(
            "[%s] 代理未开启，用直连 IP。请用住宅/手机流量，"
            "不要用共享 VPN/服务器 IP。", platform)

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    user_data_dir = os.path.join(root, "data", "browser", platform)

    # --- 1. CDP：连本机已打开的真实浏览器 ---
    if cdp_mode and connect_existing:
        try:
            browser = playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{cdp_port}", timeout=5000)
            contexts = browser.contexts
            if contexts:
                ctx = contexts[0]
                logger.info("[%s] 已连上本机真实浏览器（CDP %d）", platform, cdp_port)
            else:
                kwargs = {"viewport": {"width": 1920, "height": 1080},
                          "user_agent": ua}
                if proxy:
                    kwargs["proxy"] = proxy
                if storage_state and os.path.exists(storage_state):
                    kwargs["storage_state"] = storage_state
                ctx = browser.new_context(**kwargs)
                logger.info("[%s] 已连上本机真实浏览器（CDP %d），新建上下文", platform, cdp_port)
            try:
                ctx.add_init_script(STEALTH_INIT_SCRIPT)
            except Exception:
                pass
            return browser, ctx
        except Exception as e:  # noqa: BLE001 - 连不上就退回，不报错
            logger.info("[%s] 连本机浏览器失败（%s），退回 Playwright 自带浏览器",
                        platform, e)

    # --- 2/3. 退回：launch_persistent_context ---
    kwargs = {
        "headless": headless,
        "viewport": {"width": 1920, "height": 1080},
        "user_agent": ua,
    }
    if custom_path:
        kwargs["executable_path"] = custom_path
    if proxy:
        kwargs["proxy"] = proxy
    if storage_state and os.path.exists(storage_state):
        kwargs["storage_state"] = storage_state
    ctx = playwright.chromium.launch_persistent_context(user_data_dir, **kwargs)
    try:
        ctx.add_init_script(STEALTH_INIT_SCRIPT)
    except Exception:
        pass
    logger.info("[%s] 用 Playwright 自带浏览器，user_data_dir=%s", platform, user_data_dir)
    return ctx.browser, ctx


def close_browser(browser, context):
    """统一关闭：persistent context 只关 context，CDP 模式关 browser。"""
    try:
        if context is not None:
            context.close()
    except Exception:
        pass
    try:
        # persistent context 的 browser 就是 context.browser，关 context 已够；
        # CDP 连上来的 browser 需要显式关。重复关是安全的，包一层 try。
        if browser is not None and getattr(context, "browser", None) is not browser:
            browser.close()
    except Exception:
        pass


class BaseCollector:
    platform = "base"
    home_url = ""
    # 每个平台自己填搜索地址模板，{keyword} 会被替换
    search_url_template = ""

    def __init__(self, config: dict, db_conn, headless: bool = False):
        self.config = config
        self.conn = db_conn
        self.headless = headless
        auth_dir = config.get("storage", {}).get("auth_dir", "data/auth")
        template = config.get("browser", {}).get(
            "storage_state_template", "data/auth/{platform}.json")
        self.storage_state = template.format(platform=self.platform)
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.auth_path = os.path.join(root, self.storage_state) \
            if not os.path.isabs(self.storage_state) else self.storage_state
        self.max_contents = int(config.get("per_platform", {}).get("max_contents", 3))
        self.max_comments = int(config.get("per_platform", {}).get("max_comments_per_content", 20))
        self.consecutive_failures = 0

    def search_url(self, keyword: str) -> str:
        from urllib.parse import quote
        return self.search_url_template.format(keyword=quote(keyword))

    def has_login_state(self) -> bool:
        return os.path.exists(self.auth_path)

    def require_login(self) -> bool:
        if not self.has_login_state():
            logger.warning(
                "[%s] 未找到登录态 %s，请先运行：python -m collector.login --platform %s，"
                "在打开的浏览器里人工扫码登录，不要用脚本绕验证码。",
                self.platform, self.auth_path, self.platform)
            return False
        return True

    def pong(self, page=None) -> tuple:
        """登录健康检查，返回 (ok: bool, reason: str)。

        规则：没登录态直接 False；有 page 时打开首页，出现风控词、
        或明确出现“请登录/扫码登录”提示就 False；其他情况只要登录态
        文件存在且没触发风控，就认为还活着。绝不尝试绕验证码/滑块。
        """
        from tools.risk import detect_risk
        if not self.has_login_state():
            return False, "no login state: run collector.login first"
        if page is None:
            return True, "login state file exists"
        try:
            page.goto(self.home_url or self.search_url(""), wait_until="domcontentloaded",
                      timeout=60000)
            page.wait_for_timeout(2000)
            text = ""
            try:
                text = page.inner_text("body") or ""
            except Exception:
                text = ""
            is_risk, reason = detect_risk(text)
            if is_risk:
                return False, reason
            if "请登录" in text or "扫码登录" in text:
                return False, "页面提示请登录/扫码登录，登录态可能已过期"
            return True, "pong ok"
        except Exception as e:  # noqa: BLE001
            return False, f"pong failed: {e}"

    # --- 以下由各平台子类实现，找不到选择器时只记日志，不崩溃 ---

    def collect_contents(self, page, keyword: str):
        raise NotImplementedError

    def collect_comments(self, page, content: dict):
        raise NotImplementedError

    # --- 通用小工具 ---

    @staticmethod
    def try_text(page, selectors, timeout=3000):
        """按顺序试多个选择器，取第一个能拿到文本的；全失败返回 '' 并记日志。"""
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if el:
                    t = (el.inner_text() or "").strip()
                    if t:
                        return t
            except Exception as e:  # noqa: BLE001 - 选择器失效是预期情况
                logger.debug("selector failed %s: %s", sel, e)
        logger.warning("all selectors failed: %s", selectors[:2])
        return ""

    @staticmethod
    def scroll_down(page, times: int = 3, pause: float | None = None):
        """带随机停顿的滚动：每次滚完等 base + 随机抖动，不用固定节奏。"""
        for _ in range(times):
            try:
                page.mouse.wheel(0, random.randint(800, 1600))
            except Exception:
                try:
                    page.evaluate("window.scrollBy(0, 1200)")
                except Exception:
                    pass
            if pause is None:
                time.sleep(random.uniform(1.0, 3.0))
            else:
                time.sleep(pause)

    # --- 评论抽取通用小工具：只取叶子评论，不取容器 ---
    # 之前的问题：用 "[data-e2e='comment-list'] div, .comment-item,
    # [class*='comment']" 这种宽泛选择器，会同时命中评论列表容器、
    # 评论项和里面的子 div，同一条评论被抓多次，文本里还混着
    # 昵称+点赞数+时间，打分就被污染了。下面三个方法是修法：
    # 只取叶子项、跳过含嵌套评论项的容器、正文优先取子节点。

    @staticmethod
    def normalize_text(text) -> str:
        """把空白（换行/多空格/制表符）折叠成单个空格并去首尾。"""
        return " ".join(str(text or "").split())

    @staticmethod
    def comment_body(el, body_selectors=("[class*='comment-text']",
                                          "[class*='content']",
                                          "[class*='text']")) -> str:
        """先试正文子节点，再回退到整块 inner_text。

        正文子节点优先：容器里常混着昵称、点赞、时间、回复按钮，
        直接取整块文本会把这些都算进评论。取不到子节点时才回退。
        """
        for sel in body_selectors:
            try:
                node = el.query_selector(sel)
            except Exception:
                node = None
            if node is not None:
                try:
                    text = BaseCollector.normalize_text(node.inner_text())
                except Exception:
                    text = ""
                if len(text) >= 2:
                    return text
        try:
            return BaseCollector.normalize_text(el.inner_text())
        except Exception:
            return ""

    @staticmethod
    def has_nested_comment(el, nested_selectors) -> bool:
        """元素内部是否还含另一个评论项（是容器，不是叶子）。

        Playwright 的 query_selector 只搜后代、不含自身，
        所以叶子项返回 False，容器返回 True。
        """
        for sel in nested_selectors:
            try:
                if el.query_selector(sel) is not None:
                    return True
            except Exception:
                continue
        return False

    def _check_page_risk(self, page) -> bool:
        """页面出现风控词返回 True（调用方应立刻停）。"""
        from tools.risk import detect_risk
        try:
            text = page.inner_text("body") or ""
        except Exception:
            return False
        is_risk, reason = detect_risk(text)
        if is_risk:
            logger.error("[%s] RISK_DETECTED：%s，立刻停止整轮，不继续下一个关键词/平台。",
                         self.platform, reason)
            return True
        return False

    def run_for_keyword(self, page, keyword: str):
        """一关键词跑一轮：搜内容 -> 逐条抓评论。

        返回 (内容数, 新评论数, stopped_risk: bool)。
        风控触发或连续失败 3 次时 stopped_risk=True，调用方必须停整轮，
        不要继续下一个关键词/平台。
        """
        from tools.risk import RiskDetected
        from storage.db import save_content, save_comment
        from scoring.scorer import score_comment

        buy = self.config.get("intent_keywords", {}).get("buy", [])
        neg = self.config.get("intent_keywords", {}).get("negative", [])
        url = self.search_url(keyword)
        logger.info("[%s] 搜索关键词 %s -> %s", self.platform, keyword, url)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:  # noqa: BLE001
            self.consecutive_failures += 1
            logger.warning("[%s] 打开搜索页失败 %s", self.platform, e)
            if self.consecutive_failures >= 3:
                return 0, 0, True
            return 0, 0, False
        jitter_sleep(self.config)
        if self._check_page_risk(page):
            raise RiskDetected("risk on search page")
        contents = self.collect_contents(page, keyword) or []
        contents = contents[: self.max_contents]
        new_comments = 0
        for c in contents:
            if self.consecutive_failures >= 3:
                return len(contents), new_comments, True
            save_content(self.conn, self.platform, c.get("id", c.get("url", "")),
                         c.get("title", ""), c.get("url", ""), c.get("author", ""), keyword)
            try:
                page.goto(c["url"], wait_until="domcontentloaded", timeout=60000)
                jitter_sleep(self.config)
                if self._check_page_risk(page):
                    raise RiskDetected("risk on content page")
                self.scroll_down(page, times=3)
            except RiskDetected:
                raise
            except Exception as e:  # noqa: BLE001
                self.consecutive_failures += 1
                logger.warning("[%s] 打开内容失败 %s: %s", self.platform, c.get("url"), e)
                if self.consecutive_failures >= 3:
                    return len(contents), new_comments, True
                continue
            self.consecutive_failures = 0
            comments = self.collect_comments(page, c) or []
            for cm in comments[: self.max_comments]:
                score = score_comment(cm.get("text", ""), buy, neg)
                ok = save_comment(
                    self.conn, self.platform, c.get("id", c.get("url", "")),
                    cm.get("user_id", ""), cm.get("nickname", ""),
                    cm.get("homepage_url", ""), cm.get("text", ""),
                    cm.get("created_at", ""), cm.get("likes", 0),
                    score, cm.get("reply_to", ""))
                if ok:
                    new_comments += 1
            # 每条内容之间随机等 3-8 秒，不要固定节奏
            time.sleep(random.uniform(3.0, 8.0))
        logger.info("[%s] 关键词 %s 完成：内容 %d 条，新评论 %d 条",
                    self.platform, keyword, len(contents), new_comments)
        return len(contents), new_comments, False
