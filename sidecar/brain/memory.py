"""SQLite-backed relationship memory: interactions, sentiment, summaries, personas."""
import sqlite3
import time

_SCHEMA = """
CREATE TABLE IF NOT EXISTS interactions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_guid INTEGER NOT NULL,
    other_guid INTEGER NOT NULL,
    other_name TEXT NOT NULL,
    channel TEXT NOT NULL,
    message TEXT NOT NULL,
    reply TEXT NOT NULL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_interactions_pair ON interactions(bot_guid, other_guid, id);
CREATE TABLE IF NOT EXISTS sentiment(
    bot_guid INTEGER NOT NULL,
    other_guid INTEGER NOT NULL,
    score REAL NOT NULL DEFAULT 0,
    PRIMARY KEY(bot_guid, other_guid)
);
CREATE TABLE IF NOT EXISTS summaries(
    bot_guid INTEGER NOT NULL,
    other_guid INTEGER NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    last_id INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(bot_guid, other_guid)
);
CREATE TABLE IF NOT EXISTS personas(
    bot_guid INTEGER PRIMARY KEY,
    card TEXT NOT NULL
);
"""


class MemoryStore:
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def record_interaction(self, bot_guid: int, other_guid: int, other_name: str,
                           channel: str, message: str, reply: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO interactions(bot_guid, other_guid, other_name, channel, message, reply, ts)"
            " VALUES(?,?,?,?,?,?,?)",
            (bot_guid, other_guid, other_name, channel, message, reply, time.time()))
        self.conn.commit()
        return cur.lastrowid

    def recent(self, bot_guid: int, other_guid: int, limit: int = 8) -> list[tuple[str, str]]:
        rows = self.conn.execute(
            "SELECT message, reply FROM interactions WHERE bot_guid=? AND other_guid=?"
            " ORDER BY id DESC LIMIT ?", (bot_guid, other_guid, limit)).fetchall()
        return list(reversed(rows))

    def sentiment(self, bot_guid: int, other_guid: int) -> float:
        row = self.conn.execute(
            "SELECT score FROM sentiment WHERE bot_guid=? AND other_guid=?",
            (bot_guid, other_guid)).fetchone()
        return row[0] if row else 0.0

    def adjust_sentiment(self, bot_guid: int, other_guid: int, delta: float) -> float:
        self.conn.execute(
            "INSERT INTO sentiment(bot_guid, other_guid, score) VALUES(?,?,0)"
            " ON CONFLICT(bot_guid, other_guid) DO NOTHING",
            (bot_guid, other_guid))
        self.conn.execute(
            "UPDATE sentiment SET score = MAX(-100.0, MIN(100.0, score + ?))"
            " WHERE bot_guid=? AND other_guid=?",
            (delta, bot_guid, other_guid))
        self.conn.commit()
        return self.sentiment(bot_guid, other_guid)

    def summary(self, bot_guid: int, other_guid: int) -> tuple[str, int]:
        row = self.conn.execute(
            "SELECT summary, last_id FROM summaries WHERE bot_guid=? AND other_guid=?",
            (bot_guid, other_guid)).fetchone()
        return (row[0], row[1]) if row else ("", 0)

    def set_summary(self, bot_guid: int, other_guid: int, text: str, last_id: int) -> None:
        self.conn.execute(
            "INSERT INTO summaries(bot_guid, other_guid, summary, last_id) VALUES(?,?,?,?)"
            " ON CONFLICT(bot_guid, other_guid) DO UPDATE SET summary=excluded.summary,"
            " last_id=excluded.last_id",
            (bot_guid, other_guid, text, last_id))
        self.conn.commit()

    def unsummarized(self, bot_guid: int, other_guid: int) -> list[tuple[int, str, str]]:
        _, last_id = self.summary(bot_guid, other_guid)
        return self.conn.execute(
            "SELECT id, message, reply FROM interactions"
            " WHERE bot_guid=? AND other_guid=? AND id>? ORDER BY id",
            (bot_guid, other_guid, last_id)).fetchall()

    def get_persona(self, bot_guid: int) -> str | None:
        row = self.conn.execute(
            "SELECT card FROM personas WHERE bot_guid=?", (bot_guid,)).fetchone()
        return row[0] if row else None

    def set_persona(self, bot_guid: int, card: str) -> None:
        self.conn.execute(
            "INSERT INTO personas(bot_guid, card) VALUES(?,?)"
            " ON CONFLICT(bot_guid) DO UPDATE SET card=excluded.card",
            (bot_guid, card))
        self.conn.commit()
