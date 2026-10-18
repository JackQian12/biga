# -*- coding: utf-8 -*-
"""SQLite 存储层（标准库 sqlite3），负责建表与数据的增删改查。"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import get_config

_LOCAL = threading.local()
_SCHEMA = """
CREATE TABLE IF NOT EXISTS quotes (
    code       TEXT PRIMARY KEY,
    name       TEXT,
    price      REAL, open REAL, high REAL, low REAL,
    prev_close REAL, volume REAL, amount REAL,
    change_pct REAL, change REAL,
    update_time TEXT
);
CREATE TABLE IF NOT EXISTS fundamentals (
    code           TEXT PRIMARY KEY,
    name           TEXT,
    pe REAL, pb REAL, roe REAL, market_cap REAL,
    eps REAL, bvps REAL, revenue_growth REAL, profit_growth REAL, dividend_yield REAL,
    update_time TEXT
);
CREATE TABLE IF NOT EXISTS news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT,
    title TEXT,
    url TEXT,
    source TEXT,
    publish_time TEXT,
    summary TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_news_code ON news(code);
CREATE TABLE IF NOT EXISTS material (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT,
    code TEXT,
    content TEXT,
    source TEXT,
    metrics TEXT,
    date TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_material_date ON material(date);
CREATE INDEX IF NOT EXISTS idx_material_kind ON material(kind);
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    webhook_url TEXT,
    webhook_secret TEXT DEFAULT '',
    watch_codes TEXT DEFAULT '[]',
    enabled INTEGER DEFAULT 1,
    created_at TEXT
);
"""


def _conn(db_path: Path) -> sqlite3.Connection:
    conn = getattr(_LOCAL, "conn", None)
    if conn is None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        conn.commit()
        _LOCAL.conn = conn
        _LOCAL.db_path = db_path
    return conn


def get_conn() -> sqlite3.Connection:
    return _conn(get_config().db_path)


# ---------------- quotes ----------------
def upsert_quotes(rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    conn = get_conn()
    conn.executemany(
        """INSERT OR REPLACE INTO quotes
           (code,name,price,open,high,low,prev_close,volume,amount,change_pct,change,update_time)
           VALUES (:code,:name,:price,:open,:high,:low,:prev_close,:volume,:amount,:change_pct,:change,:update_time)""",
        rows,
    )
    conn.commit()
    return len(rows)


def get_quotes(codes: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    conn = get_conn()
    if codes:
        marks = ",".join("?" for _ in codes)
        cur = conn.execute(
            f"SELECT * FROM quotes WHERE code IN ({marks})", codes
        )
    else:
        cur = conn.execute("SELECT * FROM quotes")
    return [dict(r) for r in cur.fetchall()]


def clear_quotes() -> None:
    conn = get_conn()
    conn.execute("DELETE FROM quotes")
    conn.commit()


# ---------------- fundamentals ----------------
def upsert_fundamentals(rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    conn = get_conn()
    conn.executemany(
        """INSERT OR REPLACE INTO fundamentals
           (code,name,pe,pb,roe,market_cap,eps,bvps,revenue_growth,profit_growth,dividend_yield,update_time)
           VALUES (:code,:name,:pe,:pb,:roe,:market_cap,:eps,:bvps,:revenue_growth,:profit_growth,:dividend_yield,:update_time)""",
        rows,
    )
    conn.commit()
    return len(rows)


def get_fundamentals(codes: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    conn = get_conn()
    if codes:
        marks = ",".join("?" for _ in codes)
        cur = conn.execute(
            f"SELECT * FROM fundamentals WHERE code IN ({marks})", codes
        )
    else:
        cur = conn.execute("SELECT * FROM fundamentals")
    return [dict(r) for r in cur.fetchall()]


# ---------------- news ----------------
def insert_news(rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    conn = get_conn()
    now = datetime.now().isoformat(timespec="seconds")
    params = []
    for r in rows:
        params.append(
            (
                r.get("code"),
                r.get("title", ""),
                r.get("url", ""),
                r.get("source"),
                r.get("publish_time"),
                r.get("summary"),
                now,
            )
        )
    conn.executemany(
        """INSERT INTO news (code,title,url,source,publish_time,summary,created_at)
           VALUES (?,?,?,?,?,?,?)""",
        params,
    )
    conn.commit()
    return len(rows)


def get_news(codes: Optional[List[str]] = None, limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_conn()
    if codes:
        marks = ",".join("?" for _ in codes)
        cur = conn.execute(
            f"SELECT * FROM news WHERE code IN ({marks}) ORDER BY publish_time DESC LIMIT ?",
            [*codes, limit],
        )
    else:
        cur = conn.execute("SELECT * FROM news ORDER BY publish_time DESC LIMIT ?", (limit,))
    return [dict(r) for r in cur.fetchall()]


# ---------------- material（市场素材）----------------
def clear_material(kind: Optional[str] = None) -> None:
    conn = get_conn()
    if kind:
        conn.execute("DELETE FROM material WHERE kind=?", (kind,))
    else:
        conn.execute("DELETE FROM material")
    conn.commit()


def insert_material(rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    conn = get_conn()
    now = datetime.now().isoformat(timespec="seconds")
    params = []
    for r in rows:
        params.append((
            r.get("kind"),
            r.get("code"),
            r.get("content"),
            r.get("source"),
            json.dumps(r.get("metrics") or {}, ensure_ascii=False, default=str),
            r.get("date"),
            now,
        ))
    conn.executemany(
        """INSERT INTO material (kind,code,content,source,metrics,date,created_at)
           VALUES (?,?,?,?,?,?,?)""",
        params,
    )
    conn.commit()
    return len(rows)


def get_material(kind: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_conn()
    sql = "SELECT * FROM material"
    args: List[Any] = []
    if kind:
        sql += " WHERE kind=?"
        args.append(kind)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    rows = conn.execute(sql, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["metrics"] = json.loads(d.get("metrics") or "{}")
        except Exception:
            d["metrics"] = {}
        out.append(d)
    return out


# ---------------- subscriptions ----------------
def _parse_codes(raw) -> List[str]:
    try:
        codes = json.loads(raw) if raw else []
    except Exception:
        codes = []
    return [str(c).strip() for c in codes if str(c).strip()]


def _to_json(codes) -> str:
    return json.dumps(list(codes), ensure_ascii=False)


def add_subscription(name: str, webhook_url: str, watch_codes: Optional[List[str]] = None,
                    webhook_secret: str = "", enabled: bool = True) -> int:
    conn = get_conn()
    now = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        """INSERT INTO subscriptions (name,webhook_url,webhook_secret,watch_codes,enabled,created_at)
           VALUES (?,?,?,?,?,?)""",
        (name, webhook_url, webhook_secret, _to_json(watch_codes or []), int(enabled), now),
    )
    conn.commit()
    return cur.lastrowid


def update_subscription(sid: int, *, name: str = None, webhook_url: str = None,
                        webhook_secret: str = None, watch_codes: Optional[List[str]] = None,
                        enabled: bool = None) -> int:
    conn = get_conn()
    sets, params = [], []
    if name is not None:
        sets.append("name=?"); params.append(name)
    if webhook_url is not None:
        sets.append("webhook_url=?"); params.append(webhook_url)
    if webhook_secret is not None:
        sets.append("webhook_secret=?"); params.append(webhook_secret)
    if watch_codes is not None:
        sets.append("watch_codes=?"); params.append(_to_json(watch_codes))
    if enabled is not None:
        sets.append("enabled=?"); params.append(int(enabled))
    if not sets:
        return 0
    params.append(sid)
    cur = conn.execute(f"UPDATE subscriptions SET {','.join(sets)} WHERE id=?", params)
    conn.commit()
    return cur.rowcount


def _sub_row_to_dict(row) -> Dict[str, Any]:
    d = dict(row)
    d["watch_codes"] = _parse_codes(d.get("watch_codes"))
    d["enabled"] = bool(d.get("enabled"))
    return d


def get_subscriptions(enabled_only: bool = False) -> List[Dict[str, Any]]:
    conn = get_conn()
    sql = "SELECT * FROM subscriptions"
    if enabled_only:
        sql += " WHERE enabled=1"
    sql += " ORDER BY id"
    return [_sub_row_to_dict(r) for r in conn.execute(sql).fetchall()]


def get_subscription(sid: int) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM subscriptions WHERE id=?", (sid,)).fetchone()
    return _sub_row_to_dict(row) if row else None


def delete_subscription(sid: int) -> int:
    conn = get_conn()
    cur = conn.execute("DELETE FROM subscriptions WHERE id=?", (sid,))
    conn.commit()
    return cur.rowcount


# ---------------- meta / helpers ----------------
def get_stats() -> Dict[str, int]:
    conn = get_conn()
    return {
        "quotes": conn.execute("SELECT COUNT(*) FROM quotes").fetchone()[0],
        "fundamentals": conn.execute("SELECT COUNT(*) FROM fundamentals").fetchone()[0],
        "news": conn.execute("SELECT COUNT(*) FROM news").fetchone()[0],
    }


def to_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)
