# -*- coding: utf-8 -*-
"""配置界面离线测试：不联网、不开浏览器、不跑真实采集。
测 GET/POST /api/config 的校验与保存、备份、以及 /api/run/status 初始状态。
用法：python -m tests.test_config_ui
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

import app.app as app_mod  # noqa: E402


def _req(port, method, path, payload=None):
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"error": body}


class TestConfigUI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg_path = os.path.join(self.tmp.name, "config.yaml")
        shutil.copyfile(os.path.join(ROOT, "config.yaml"), self.cfg_path)
        with open(self.cfg_path, encoding="utf-8") as f:
            self.before_text = f.read()
        app_mod.CONFIG_PATH_OVERRIDE = self.cfg_path
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app_mod.Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        try:
            self.server.shutdown()
            self.server.server_close()
        except Exception:
            pass
        app_mod.CONFIG_PATH_OVERRIDE = None
        self.tmp.cleanup()

    def test_get_config_returns_five_platforms(self):
        code, body = _req(self.port, "GET", "/api/config")
        self.assertEqual(code, 200)
        self.assertEqual(set(body["platforms"]),
                         {"douyin", "xiaohongshu", "bilibili", "weibo", "tieba"})
        self.assertTrue(body["product_name"])
        self.assertIsInstance(body["keywords"], list)
        self.assertGreaterEqual(len(body["keywords"]), 1)

    def test_post_valid_config_saves_and_reloads(self):
        payload = {
            "product_name": "测试产品",
            "product_intro": "测试介绍",
            "keywords": ["手机壳", "耳机"],
            "platforms": ["douyin", "bilibili"],
            "per_platform": {"max_contents": 5, "max_comments_per_content": 30},
            "intent_keywords": {"buy": "多少钱，哪里买", "negative": "广告"},
            "sender_limits": {"max_per_day_per_platform": 10, "min_delay_seconds": 60,
                              "max_delay_seconds": 120, "active_hours_start": 9,
                              "active_hours_end": 21},
        }
        code, body = _req(self.port, "POST", "/api/config", payload)
        self.assertEqual(code, 200, body)
        self.assertTrue(body.get("ok"))
        # 备份存在，且是旧内容
        bak = self.cfg_path + ".bak"
        self.assertTrue(os.path.exists(bak))
        with open(bak, encoding="utf-8") as f:
            self.assertIn("示例产品", f.read())
        # 磁盘文件已更新，且 GET 能读回
        with open(self.cfg_path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("测试产品", text)
        self.assertIn("手机壳", text)
        code2, body2 = _req(self.port, "GET", "/api/config")
        self.assertEqual(code2, 200)
        self.assertEqual(body2["product_name"], "测试产品")
        self.assertEqual(body2["keywords"], ["手机壳", "耳机"])
        self.assertEqual(body2["platforms"], ["douyin", "bilibili"])
        self.assertEqual(body2["per_platform"]["max_contents"], 5)
        # 逗号字符串在 YAML 里存为列表
        self.assertEqual(body2["intent_keywords"]["buy"], ["多少钱", "哪里买"])
        self.assertEqual(body2["intent_keywords"]["negative"], ["广告"])
        # 其他节（storage / browser）仍保留
        self.assertIn("data/leads.db", text)

    def test_post_invalid_does_not_overwrite(self):
        bad_payloads = [
            # 空关键词
            {"product_name": "测试产品", "keywords": [], "platforms": ["douyin"]},
            # 关键词全空字符串
            {"product_name": "测试产品", "keywords": ["  ", ""], "platforms": ["douyin"]},
            # 不支持的平台
            {"product_name": "测试产品", "keywords": ["手机壳"], "platforms": ["douyin", "nope"]},
            # 平台为空
            {"product_name": "测试产品", "keywords": ["手机壳"], "platforms": []},
            # max_contents 超限
            {"product_name": "测试产品", "keywords": ["手机壳"], "platforms": ["douyin"],
             "per_platform": {"max_contents": 999, "max_comments_per_content": 20}},
            # 延迟 min > max
            {"product_name": "测试产品", "keywords": ["手机壳"], "platforms": ["douyin"],
             "sender_limits": {"min_delay_seconds": 300, "max_delay_seconds": 60}},
            # 时段 start >= end
            {"product_name": "测试产品", "keywords": ["手机壳"], "platforms": ["douyin"],
             "sender_limits": {"active_hours_start": 21, "active_hours_end": 9}},
            # 产品名为空
            {"product_name": "  ", "keywords": ["手机壳"], "platforms": ["douyin"]},
        ]
        for payload in bad_payloads:
            code, body = _req(self.port, "POST", "/api/config", payload)
            self.assertEqual(code, 400, (payload, body))
            self.assertIn("error", body)
            with open(self.cfg_path, encoding="utf-8") as f:
                self.assertEqual(f.read(), self.before_text)

    def test_run_status_not_running_initially(self):
        code, body = _req(self.port, "GET", "/api/run/status")
        self.assertEqual(code, 200)
        self.assertFalse(body["running"])
        self.assertIn("last_lines", body)
        self.assertIsInstance(body["last_lines"], list)

    def test_run_post_invalid_returns_400(self):
        code, body = _req(self.port, "POST", "/api/run",
                          {"platforms": [], "keyword": "手机壳"})
        self.assertEqual(code, 400)
        code, body = _req(self.port, "POST", "/api/run",
                          {"platforms": ["douyin"], "keyword": ""})
        self.assertEqual(code, 400)
        code, body = _req(self.port, "POST", "/api/run",
                          {"platforms": ["nope"], "keyword": "手机壳"})
        self.assertEqual(code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
