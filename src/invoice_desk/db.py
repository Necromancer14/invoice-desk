"""Tiny SQLite wrapper: one connection, a lock, WAL, JSON helpers."""
from __future__ import annotations

import json
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT, content_type TEXT, blob BLOB, source TEXT, size INTEGER,
  status TEXT, mode TEXT, fields TEXT, extraction TEXT, results TEXT, rules_version INTEGER, error TEXT,
  decision_by TEXT, decision_note TEXT, final_fields TEXT, edited INTEGER DEFAULT 0, decided_at TEXT,
  created_at TEXT, updated_at TEXT, submitted_by TEXT, trace TEXT);
CREATE INDEX IF NOT EXISTS runs_status ON runs(status);
CREATE TABLE IF NOT EXISTS rules(key TEXT PRIMARY KEY, position INTEGER, name TEXT, type TEXT, params TEXT,
  severity TEXT, enabled INTEGER, message TEXT);
CREATE TABLE IF NOT EXISTS rule_versions(version INTEGER PRIMARY KEY AUTOINCREMENT, snapshot TEXT, author TEXT, note TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT, action TEXT, target TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS vendors(id INTEGER PRIMARY KEY AUTOINCREMENT, name_en TEXT, name_ar TEXT, vat TEXT, iban TEXT,
  currency TEXT, status TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS vendor_aliases(id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id INTEGER, alias TEXT, key TEXT UNIQUE,
  created_by TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS purchase_orders(id INTEGER PRIMARY KEY AUTOINCREMENT, po_number TEXT UNIQUE, vendor_id INTEGER,
  vendor_name TEXT, amount REAL, currency TEXT, status TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS eval_results(provider TEXT, model TEXT, sample_id TEXT, outcome TEXT, evaluated_at TEXT,
  rules_version INTEGER, row TEXT, PRIMARY KEY(provider, model, sample_id));
"""


class DB:
    def __init__(self, path: str = ":memory:"):
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        if path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def run(self, sql: str, args=()):
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    def all(self, sql: str, args=()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql: str, args=()):
        rows = self.all(sql, args)
        return rows[0] if rows else None


def dumps(x) -> str:
    return json.dumps(x, ensure_ascii=False)


def loads(s, default=None):
    if s is None or s == "":
        return default
    return json.loads(s)
