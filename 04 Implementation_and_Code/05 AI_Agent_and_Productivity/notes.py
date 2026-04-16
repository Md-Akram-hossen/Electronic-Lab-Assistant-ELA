from __future__ import annotations

import sqlite3
from threading import Lock

from .config import get_settings

notes_lock = Lock()


def ensure_notes_db() -> None:
    settings = get_settings()
    conn = sqlite3.connect(settings.notes_db)
    cur = conn.cursor()
    for table in ("notes", "tasks"):
        cur.execute(
            f'''
            CREATE TABLE IF NOT EXISTS {table} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                num INTEGER,
                text TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        cols = [row[1].lower() for row in cur.execute(f"PRAGMA table_info({table})").fetchall()]
        if "num" not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN num INTEGER")
        rows = cur.execute(f"SELECT id FROM {table} ORDER BY id").fetchall()
        for num, (row_id,) in enumerate(rows, start=1):
            cur.execute(f"UPDATE {table} SET num=? WHERE id=?", (num, row_id))
        cur.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_num ON {table}(num)")
    conn.commit()
    conn.close()


def _next_num(cur, table: str) -> int:
    return int(cur.execute(f"SELECT COALESCE(MAX(num), 0) + 1 FROM {table}").fetchone()[0])


def add_item(table: str, text: str) -> int | None:
    if table not in {"notes", "tasks"} or not (text or "").strip():
        return None
    settings = get_settings()
    with notes_lock:
        conn = sqlite3.connect(settings.notes_db)
        cur = conn.cursor()
        num = _next_num(cur, table)
        cur.execute(f"INSERT INTO {table}(num, text) VALUES(?, ?)", (num, text.strip()))
        conn.commit()
        conn.close()
        return num


def list_items(table: str, limit: int = 10):
    if table not in {"notes", "tasks"}:
        return []
    settings = get_settings()
    with notes_lock:
        conn = sqlite3.connect(settings.notes_db)
        rows = conn.execute(f"SELECT num, text, created_at FROM {table} ORDER BY num").fetchall()
        conn.close()
    return rows[-limit:] if limit and len(rows) > limit else rows


def delete_item_by_num(table: str, num: int) -> bool:
    if table not in {"notes", "tasks"} or num <= 0:
        return False
    settings = get_settings()
    with notes_lock:
        conn = sqlite3.connect(settings.notes_db)
        cur = conn.cursor()
        cur.execute(f"DELETE FROM {table} WHERE num=?", (num,))
        ok = cur.rowcount > 0
        if ok:
            cur.execute(f"UPDATE {table} SET num = num - 1 WHERE num > ?", (num,))
        conn.commit()
        conn.close()
        return ok
