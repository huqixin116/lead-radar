# -*- coding: utf-8 -*-
"""离线 Mock 测试：不联网、不开浏览器，测打分、存库、去重、队列、导出、草稿。
用法：python -m tests.test_mock
或：   python tests/test_mock.py
"""
from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)


class TestMock(unittest.TestCase):
    def setUp(self):
        from storage.db import init_db
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "leads.db")
        self.conn = init_db(self.db_path)
        with open(os.path.join(ROOT, "sample_data", "sample_comments.json"),
                  encoding="utf-8") as f:
            self.samples = json.load(f)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_sample_covers_all_five_platforms(self):
        platforms = {s["platform"] for s in self.samples}
        self.assertEqual(platforms,
                         {"douyin", "xiaohongshu", "bilibili", "weibo", "tieba"})
        self.assertEqual(len(self.samples), 10)

    def test_scorer_buy_intent_high(self):
        from scoring.scorer import score_comment
        self.assertGreaterEqual(score_comment("这个多少钱？哪里买？求链接"), 3)
        self.assertGreaterEqual(score_comment("想买一个，300元以内有推荐吗？"), 3)
        self.assertGreaterEqual(score_comment("怎么买？有链接吗，入手一个试试"), 3)
        self.assertLessEqual(score_comment("哈哈哈哈太好笑了"), 1)
        self.assertLessEqual(score_comment("前排"), 1)
        self.assertLessEqual(score_comment("加微信免费送，抽奖了解一下"), 1)
        self.assertLessEqual(score_comment("别买，垃圾"), 1)

    def test_storage_dedup_and_leads(self):
        from storage.db import save_content, save_comment, list_leads
        from scoring.scorer import score_comment
        for s in self.samples:
            save_content(self.conn, s["platform"], s["content_id"], s["title"],
                         s["url"], "", "示例关键词1")
            save_comment(self.conn, s["platform"], s["content_id"], s["user_id"],
                         s["nickname"], s["homepage_url"], s["text"],
                         likes=s["likes"], score=score_comment(s["text"]))
        # 重跑一次同一批，应全部去重，不新增
        n1 = len(list_leads(self.conn, min_score=0))
        for s in self.samples:
            save_comment(self.conn, s["platform"], s["content_id"], s["user_id"],
                         s["nickname"], s["homepage_url"], s["text"],
                         likes=s["likes"], score=score_comment(s["text"]))
        n2 = len(list_leads(self.conn, min_score=0))
        self.assertEqual(n1, 10)
        self.assertEqual(n2, 10)
        high = list_leads(self.conn, min_score=3)
        self.assertGreaterEqual(len(high), 3)
        self.assertTrue(all(r["score"] >= 3 for r in high))

    def test_queue_and_export_and_draft(self):
        from storage.db import (save_content, save_comment, list_leads,
                                create_queue_from_comments, list_queue,
                                update_queue_status, export_csv)
        from scoring.scorer import score_comment, make_draft
        for s in self.samples:
            save_content(self.conn, s["platform"], s["content_id"], s["title"],
                         s["url"], "", "示例关键词1")
            save_comment(self.conn, s["platform"], s["content_id"], s["user_id"],
                         s["nickname"], s["homepage_url"], s["text"],
                         likes=s["likes"], score=score_comment(s["text"]))
        created = create_queue_from_comments(
            self.conn, min_score=2,
            draft_fn=lambda lead: make_draft("示例产品", "示例介绍", lead))
        self.assertGreater(created, 0)
        q = list_queue(self.conn, status="pending_review")
        self.assertEqual(len(q), created)
        self.assertTrue(all(x["draft_text"] for x in q))
        # 批准一条，但不发
        update_queue_status(self.conn, q[0]["id"], "approved")
        approved = list_queue(self.conn, status="approved")
        self.assertEqual(len(approved), 1)
        out = os.path.join(self.tmp.name, "leads.csv")
        export_csv(self.conn, out, min_score=2)
        with open(out, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        self.assertGreater(len(rows), 0)
        self.assertIn("nickname", rows[0])
        self.assertIn("comment", rows[0])

    def test_sender_daily_cap_logic(self):
        # 只测计数逻辑，不开浏览器、不发消息
        from storage.db import (save_content, save_comment, create_queue_from_comments,
                                list_queue, update_queue_status, count_sent_today)
        from scoring.scorer import score_comment
        for s in self.samples[:2]:
            save_content(self.conn, s["platform"], s["content_id"], s["title"],
                         s["url"], "", "示例关键词1")
            save_comment(self.conn, s["platform"], s["content_id"], s["user_id"],
                         s["nickname"], s["homepage_url"], s["text"],
                         likes=s["likes"], score=score_comment(s["text"]))
        create_queue_from_comments(self.conn, min_score=0, draft_fn=lambda l: "草稿")
        q = list_queue(self.conn)
        self.assertEqual(count_sent_today(self.conn, q[0]["platform"]), 0)
        update_queue_status(self.conn, q[0]["id"], "sent", sent=True)
        self.assertEqual(count_sent_today(self.conn, q[0]["platform"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
