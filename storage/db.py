# -*- coding: utf-8 -*-
"""SQLite 存储：内容、评论、获客名单、外联队列。只用标准库。"""
from __future__ import annotations

import csv
import hashlib
import os
import sqlite3
from datetime import datetime, date

SCHEMA = """
CREATE TABLE IF NOT EXISTS contents (
    platform TEXT NOT NULL,
    content_id TEXT NOT NULL,
    title TEXT DEFAULT '',
    url TEXT DEFAULT '',
    author TEXT DEFAULT '',
    keyword TEXT DEFAULT '',
    crawled_at TEXT NOT NULL,
    PRIMARY KEY (platform, content_id)
);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    content_id TEXT NOT NULL,
    user_id TEXT DEFAULT '',
    nickname TEXT DEFAULT '',
    homepage_url TEXT DEFAULT '',
    text TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    created_at TEXT DEFAULT '',
    likes INTEGER DEFAULT 0,
    score INTEGER DEFAULT 0,
    reply_to TEXT DEFAULT '',
    UNIQUE(platform, content_id, user_id, text_hash)
);
CREATE TABLE IF NOT EXISTS outreach_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    comment_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    target_url TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending_review',
    draft_text TEXT DEFAULT '',
    attempts INTEGER DEFAULT 0,
    last_error TEXT DEFAULT '',
    sent_at TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(comment_id)
);
CREATE INDEX IF NOT EXISTS idx_comments_score ON comments(score DESC);
CREATE INDEX IF NOT EXISTS idx_queue_status ON outreach_queue(status);
"""


def _text_hash(text: str) -> str:
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()[:32]


def init_db(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def save_content(conn, platform, content_id, title, url, author, keyword) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO contents
           (platform, content_id, title, url, author, keyword, crawled_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (platform, content_id, title or "", url or "", author or "",
         keyword or "", datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()


def save_comment(conn, platform, content_id, user_id, nickname, homepage_url,
                 text, created_at="", likes=0, score=0, reply_to="") -> bool:
    """返回 True=新入库，False=已去重跳过。"""
    if not (text or "").strip():
        return False
    try:
        conn.execute(
            """INSERT INTO comments
               (platform, content_id, user_id, nickname, homepage_url, text,
                text_hash, created_at, likes, score, reply_to)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (platform, content_id, user_id or "", nickname or "",
             homepage_url or "", text.strip(), _text_hash(text),
             created_at or "", int(likes or 0), int(score or 0), reply_to or ""),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def update_comment_score(conn, comment_id: int, score: int) -> None:
    conn.execute("UPDATE comments SET score=? WHERE id=?", (int(score), comment_id))
    conn.commit()


def list_leads(conn, min_score: int = 0, platform: str = "", limit: int = 500):
    sql = """SELECT c.*, ct.title AS content_title, ct.url AS content_url
             FROM comments c LEFT JOIN contents ct
               ON ct.platform=c.platform AND ct.content_id=c.content_id
             WHERE c.score >= ?"""
    params: list = [min_score]
    if platform:
        sql += " AND c.platform=?"
        params.append(platform)
    sql += " ORDER BY c.score DESC, c.likes DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def create_queue_from_comments(conn, min_score: int = 2, draft_fn=None) -> int:
    """把高意向评论放进待审队列。不自动发，只待人工审。"""
    leads = list_leads(conn, min_score=min_score, limit=1000)
    created = 0
    for lead in leads:
        draft = draft_fn(lead) if draft_fn else ""
        try:
            conn.execute(
                """INSERT OR IGNORE INTO outreach_queue
                   (comment_id, platform, target_url, status, draft_text, created_at)
                   VALUES (?, ?, ?, 'pending_review', ?, ?)""",
                (lead["id"], lead["platform"],
                 lead.get("homepage_url") or lead.get("content_url") or "",
                 draft, datetime.now().isoformat(timespec="seconds")),
            )
            if conn.total_changes:
                created += 1
            conn.commit()
        except sqlite3.IntegrityError:
            continue
    return created


def list_queue(conn, status: str = "", limit: int = 200):
    sql = """SELECT q.*, c.nickname, c.text AS comment_text, c.score,
                    c.homepage_url, ct.title AS content_title, ct.url AS content_url
             FROM outreach_queue q
             LEFT JOIN comments c ON c.id=q.comment_id
             LEFT JOIN contents ct ON ct.platform=c.platform AND ct.content_id=c.content_id"""
    params: list = []
    if status:
        sql += " WHERE q.status=?"
        params.append(status)
    sql += " ORDER BY c.score DESC, q.id ASC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_queue_item(conn, queue_id: int):
    row = conn.execute(
        """SELECT q.*, c.nickname, c.text AS comment_text, c.score,
                  c.homepage_url, ct.title AS content_title, ct.url AS content_url
           FROM outreach_queue q
           LEFT JOIN comments c ON c.id=q.comment_id
           LEFT JOIN contents ct ON ct.platform=c.platform AND ct.content_id=c.content_id
           WHERE q.id=?""",
        (queue_id,),
    ).fetchone()
    return dict(row) if row else None


def update_queue_status(conn, queue_id: int, status: str, error: str = "", sent: bool = False) -> None:
    if sent:
        conn.execute(
            "UPDATE outreach_queue SET status=?, last_error=?, sent_at=?, attempts=attempts+1 WHERE id=?",
            (status, error or "", datetime.now().isoformat(timespec="seconds"), queue_id),
        )
    else:
        conn.execute(
            "UPDATE outreach_queue SET status=?, last_error=? WHERE id=?",
            (status, error or "", queue_id),
        )
    conn.commit()


def count_sent_today(conn, platform: str, on_date: str | None = None) -> int:
    d = on_date or date.today().isoformat()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM outreach_queue WHERE platform=? AND status='sent' AND sent_at LIKE ?",
        (platform, d + "%"),
    ).fetchone()
    return int(row["n"]) if row else 0


def count_sent_in_last_hour(conn, platform: str, hours: float = 1.0) -> int:
    """过去 N 小时内已发送条数（按 sent_at 时间戳算）。"""
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(hours=float(hours))).isoformat(timespec="seconds")
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM outreach_queue "
        "WHERE platform=? AND status='sent' AND sent_at >= ?",
        (platform, cutoff),
    ).fetchone()
    return int(row["n"]) if row else 0


def get_last_sent_draft(conn, platform: str) -> str:
    """该平台最近一条已发送的草稿文本，没有返回 ''。用于避免连续发相同话术。"""
    row = conn.execute(
        "SELECT draft_text FROM outreach_queue WHERE platform=? AND status='sent' "
        "ORDER BY sent_at DESC LIMIT 1",
        (platform,),
    ).fetchone()
    return str(row["draft_text"]) if row and row["draft_text"] else ""


def export_csv(conn, out_path: str, min_score: int = 0) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    leads = list_leads(conn, min_score=min_score, limit=10000)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["platform", "score", "nickname", "user_id", "homepage_url",
                    "comment", "content_title", "content_url", "likes", "created_at"])
        for r in leads:
            w.writerow([r.get("platform", ""), r.get("score", 0), r.get("nickname", ""),
                        r.get("user_id", ""), r.get("homepage_url", ""),
                        r.get("text", ""), r.get("content_title", ""),
                        r.get("content_url", ""), r.get("likes", 0),
                        r.get("created_at", "")])
    return out_path
