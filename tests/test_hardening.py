# -*- coding: utf-8 -*-
"""加固离线测试：不联网、不开浏览器、不跑真实采集。
用法：python -m tests.test_hardening
"""
from __future__ import annotations

import os
import random
import sys
import time
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from proxy.pool import ProxyPool, StaticProxyProvider, get_playwright_proxy  # noqa: E402
from tools.retry import call_with_retry, is_retryable_error  # noqa: E402
from tools.risk import detect_risk  # noqa: E402
from tools.ua import DESKTOP_UAS, get_user_agent  # noqa: E402
from collector.base import get_jitter_delay  # noqa: E402


class FakeHttpError(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class TestUA(unittest.TestCase):
    def test_rotation_returns_different_uas_over_20_calls(self):
        rng = random.Random(42)
        seen = {get_user_agent(rng) for _ in range(20)}
        self.assertGreaterEqual(len(seen), 2)
        for ua in seen:
            self.assertIn(ua, DESKTOP_UAS)
            self.assertIn("Chrome/", ua)


class TestRetry(unittest.TestCase):
    def test_does_not_retry_on_403(self):
        calls = {"n": 0}

        def boom():
            calls["n"] += 1
            raise FakeHttpError(403)

        with self.assertRaises(FakeHttpError):
            call_with_retry(boom, sleep_fn=lambda s: None)
        self.assertEqual(calls["n"], 1)

    def test_does_not_retry_on_captcha_text(self):
        calls = {"n": 0}

        def boom():
            calls["n"] += 1
            raise RuntimeError("请完成滑块验证")

        with self.assertRaises(RuntimeError):
            call_with_retry(boom, sleep_fn=lambda s: None)
        self.assertEqual(calls["n"], 1)

    def test_retries_transient_then_succeeds(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ConnectionError("reset by peer")
            return "ok"

        self.assertEqual(call_with_retry(flaky, sleep_fn=lambda s: None), "ok")
        self.assertEqual(calls["n"], 3)
        self.assertTrue(is_retryable_error(ConnectionError("x")))
        self.assertFalse(is_retryable_error(FakeHttpError(429)))


class TestRisk(unittest.TestCase):
    def test_flags_captcha_login_ip_block(self):
        for text in ["请完成验证码", "滑块验证", "登录已过期，请重新登录",
                     "操作频繁", "访问受限", "IP 被封", "私信受限"]:
            is_risk, reason = detect_risk(text)
            self.assertTrue(is_risk, text)
            self.assertTrue(reason)
        is_risk, _ = detect_risk("anything", status=429)
        self.assertTrue(is_risk)
        is_risk, _ = detect_risk("anything", status=403)
        self.assertTrue(is_risk)

    def test_does_not_flag_normal_text(self):
        for text in ["这条视频很有意思", "多少钱？哪里买？",
                     "求链接，想入手一个", "这个好用吗？推荐吗", ""]:
            is_risk, _ = detect_risk(text)
            self.assertFalse(is_risk, text)
        is_risk, _ = detect_risk("normal", status=200)
        self.assertFalse(is_risk)


class TestProxyPool(unittest.TestCase):
    def test_expiry_and_refresh(self):
        pool = ProxyPool(["http://proxy1:8080"], expiry_seconds=3600)
        self.assertEqual(pool.get_proxy(), "http://proxy1:8080")
        # 手动把过期时间调到过去：应判定过期、取不到
        pool._entries[0]["expires_at"] = time.time() - 1
        self.assertIsNone(pool.get_proxy())
        # get_or_refresh 用 loader 重新加载后又能取到
        got = pool.get_or_refresh(loader=lambda: ["http://proxy2:8080"])
        self.assertEqual(got, "http://proxy2:8080")

    def test_static_provider_and_playwright_proxy(self):
        self.assertEqual(StaticProxyProvider("http://a:1").load(), ["http://a:1"])
        self.assertEqual(StaticProxyProvider("").load(), [])
        cfg_off = {"proxy": {"enable_ip_proxy": False, "static_proxy_url": "http://a:1"}}
        self.assertIsNone(get_playwright_proxy(cfg_off))
        cfg_on = {"proxy": {"enable_ip_proxy": True, "static_proxy_url": "http://a:1"}}
        self.assertEqual(get_playwright_proxy(cfg_on), {"server": "http://a:1"})
        cfg_empty = {"proxy": {"enable_ip_proxy": True, "static_proxy_url": ""}}
        self.assertIsNone(get_playwright_proxy(cfg_empty))

    def test_validate_with_fake_opener(self):
        pool = ProxyPool(["http://proxy1:8080"])

        class Resp:
            status = 200

        self.assertTrue(pool.validate("http://proxy1:8080", opener=lambda u: Resp()))
        self.assertFalse(pool.validate(
            "http://proxy1:8080",
            opener=lambda u: (_ for _ in ()).throw(RuntimeError("timeout"))))


class TestJitter(unittest.TestCase):
    def test_jitter_within_bounds(self):
        cfg = {"crawler": {"max_sleep_sec": 2, "jitter_sec": 3}}
        rng = random.Random(1)
        for _ in range(20):
            d = get_jitter_delay(cfg, rng=rng)
            self.assertGreaterEqual(d, 2.0)
            self.assertLessEqual(d, 5.0)


class TestConfigValidation(unittest.TestCase):
    def test_rejects_concurrency_over_1_and_per_hour_over_10(self):
        import app.app as app_mod
        existing = {
            "product_name": "测试产品", "keywords": ["手机壳"],
            "platforms": ["douyin"],
            "per_platform": {"max_contents": 3, "max_comments_per_content": 20},
            "intent_keywords": {"buy": [], "negative": []},
            "sender_limits": {"max_per_day_per_platform": 20,
                              "max_per_hour_per_platform": 5,
                              "min_delay_seconds": 60, "max_delay_seconds": 180,
                              "active_hours_start": 9, "active_hours_end": 21},
            "browser": {"cdp_mode": True, "cdp_port": 9222},
            "proxy": {"enable_ip_proxy": False, "static_proxy_url": ""},
            "crawler": {"max_sleep_sec": 2, "jitter_sec": 3, "max_concurrency": 1},
        }
        _, err = app_mod._validate_config_payload(
            {"crawler": {"max_concurrency": 2}}, existing)
        self.assertIsNotNone(err)
        _, err = app_mod._validate_config_payload(
            {"sender_limits": {"max_per_hour_per_platform": 11}}, existing)
        self.assertIsNotNone(err)
        _, err = app_mod._validate_config_payload(
            {"proxy": {"enable_ip_proxy": True, "static_proxy_url": ""}}, existing)
        self.assertIsNotNone(err)
        merged, err = app_mod._validate_config_payload(
            {"crawler": {"max_concurrency": 1},
             "sender_limits": {"max_per_hour_per_platform": 5}}, existing)
        self.assertIsNone(err)
        self.assertEqual(merged["crawler"]["max_concurrency"], 1)
        self.assertEqual(merged["sender_limits"]["max_per_hour_per_platform"], 5)


class _FakeEl:
    """最小的 Playwright 元素替身：inner_text + 后代 query_selector。"""

    def __init__(self, text, children=None):
        self._text = text
        self._children = children or {}

    def inner_text(self):
        return self._text

    def query_selector(self, sel):
        return self._children.get(sel)


class TestLeafCommentExtraction(unittest.TestCase):
    def test_normalize_collapses_whitespace(self):
        from collector.base import BaseCollector
        self.assertEqual(BaseCollector.normalize_text("  多少\n钱？  哪里\n买  "),
                         "多少 钱？ 哪里 买")

    def test_comment_body_prefers_child_node_over_container(self):
        from collector.base import BaseCollector
        # 容器文本混着昵称+点赞+时间，正文子节点才是干净评论。
        body = _FakeEl("多少钱？哪里买？")
        el = _FakeEl("昵称A  123赞  2小时前  多少钱？哪里买？  回复",
                     {"[class*='comment-text']": body})
        self.assertEqual(BaseCollector.comment_body(el), "多少钱？哪里买？")

    def test_comment_body_falls_back_to_whole_text(self):
        from collector.base import BaseCollector
        el = _FakeEl("  想买一个  ")
        self.assertEqual(BaseCollector.comment_body(el), "想买一个")

    def test_has_nested_comment_skips_containers(self):
        from collector.base import BaseCollector
        leaf = _FakeEl("多少钱？")
        container = _FakeEl("容器文本", {".comment-item": leaf})
        self.assertFalse(BaseCollector.has_nested_comment(
            leaf, (".comment-item",)))
        self.assertTrue(BaseCollector.has_nested_comment(
            container, (".comment-item",)))

    def test_douyin_collector_dedups_normalized_text(self):
        # 用假 page 跑 DouyinCollector.collect_comments：容器 + 两条
        # 只有空白不同的同一评论，应只留一条，且正文取子节点。
        from collector.douyin import DouyinCollector
        body = _FakeEl("多少钱？\n哪里买？")
        leaf1 = _FakeEl("昵称  多少钱？哪里买？",
                        {"[class*='comment-text']": body,
                         "a[href*='/user/']": None})
        leaf2 = _FakeEl("昵称   多少钱？   哪里买？",
                        {"[class*='comment-text']": _FakeEl("多少钱？   哪里买？"),
                         "a[href*='/user/']": None})
        container = _FakeEl("容器", {".comment-item": leaf1})

        class FakePage:
            def query_selector_all(self, sel):
                return [container, leaf1, leaf2]

        cfg = {"per_platform": {"max_contents": 3, "max_comments_per_content": 20},
               "storage": {"auth_dir": "data/auth"},
               "browser": {"storage_state_template": "data/auth/{platform}.json"}}
        import sqlite3
        col = DouyinCollector(cfg, sqlite3.connect(":memory:"))
        col.scroll_down = lambda page, times=3, pause=None: None
        out = col.collect_comments(FakePage(), {"url": "https://www.douyin.com/video/1"})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["text"], "多少钱？ 哪里买？")


class TestMinScoreValidation(unittest.TestCase):
    def test_bad_min_score_returns_400_not_500(self):
        import app.app as app_mod
        for raw in ("abc", "1.5", "99", "-1", ""):
            value, err = app_mod._parse_min_score({"min_score": [raw]})
            self.assertIsNone(value, raw)
            self.assertIn("min_score", err)
        value, err = app_mod._parse_min_score({"min_score": ["2"]})
        self.assertEqual(value, 2)
        self.assertIsNone(err)
        value, err = app_mod._parse_min_score({})
        self.assertEqual(value, 0)


class TestDraftVariation(unittest.TestCase):
    def test_three_variants_differ_and_pick_avoids_last(self):
        from scoring.scorer import make_draft_variants, pick_draft_variant
        lead = {"nickname": "用户A", "content_title": "测试视频",
                "text": "多少钱？哪里买？"}
        variants = make_draft_variants("测试产品", "测试介绍", lead)
        self.assertEqual(len(variants), 3)
        self.assertEqual(len(set(variants)), 3)
        self.assertNotIn("微信", "".join(variants))
        picked = pick_draft_variant("测试产品", "测试介绍", lead,
                                    last_sent_draft=variants[0])
        self.assertNotEqual(picked, variants[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
