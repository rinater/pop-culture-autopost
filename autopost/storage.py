import os
import sqlite3
import time

from .sources import Item

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    url TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT,
    source TEXT NOT NULL,
    image TEXT,
    published_ts INTEGER NOT NULL,
    first_seen INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'new'
);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status, published_ts);
CREATE TABLE IF NOT EXISTS posted (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    ts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (
    k TEXT PRIMARY KEY,
    v INTEGER NOT NULL
);
"""


class Storage:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    @staticmethod
    def _row(r) -> Item:
        return Item(url=r[0], title=r[1], summary=r[2] or "", source=r[3],
                    image=r[4], published_ts=r[5])

    def add_item(self, it: Item) -> bool:
        cur = self.db.execute(
            "INSERT OR IGNORE INTO items (url, title, summary, source, image, published_ts, first_seen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (it.url, it.title, it.summary, it.source, it.image, it.published_ts, int(time.time())),
        )
        return cur.rowcount == 1

    def pending(self, since_ts: int) -> list[Item]:
        rows = self.db.execute(
            "SELECT url, title, summary, source, image, published_ts FROM items "
            "WHERE status = 'new' AND published_ts >= ? ORDER BY published_ts DESC",
            (since_ts,),
        ).fetchall()
        return [self._row(r) for r in rows]

    def window(self, since_ts: int) -> list[Item]:
        rows = self.db.execute(
            "SELECT url, title, summary, source, image, published_ts FROM items "
            "WHERE published_ts >= ?",
            (since_ts,),
        ).fetchall()
        return [self._row(r) for r in rows]

    def set_status(self, urls: list[str], status: str) -> None:
        self.db.executemany("UPDATE items SET status = ? WHERE url = ?",
                            [(status, u) for u in urls])

    def posted_titles(self, since_ts: int) -> list[str]:
        rows = self.db.execute(
            "SELECT title FROM posted WHERE ts >= ? ORDER BY ts DESC", (since_ts,)
        ).fetchall()
        return [r[0] for r in rows]

    def mark_posted(self, titles: list[str]) -> None:
        now = int(time.time())
        self.db.executemany("INSERT INTO posted (title, ts) VALUES (?, ?)",
                            [(t, now) for t in titles])

    def bump_llm_calls(self) -> None:
        key = "llm:" + time.strftime("%Y-%m-%d", time.gmtime())
        self.db.execute(
            "INSERT INTO kv (k, v) VALUES (?, 1) ON CONFLICT(k) DO UPDATE SET v = v + 1", (key,)
        )

    def llm_calls_today(self) -> int:
        key = "llm:" + time.strftime("%Y-%m-%d", time.gmtime())
        row = self.db.execute("SELECT v FROM kv WHERE k = ?", (key,)).fetchone()
        return row[0] if row else 0

    def purge(self, older_than_ts: int) -> None:
        self.db.execute("DELETE FROM items WHERE published_ts < ?", (older_than_ts,))
        self.db.execute("DELETE FROM posted WHERE ts < ?", (older_than_ts,))

    def close(self) -> None:
        self.db.commit()
        self.db.close()
