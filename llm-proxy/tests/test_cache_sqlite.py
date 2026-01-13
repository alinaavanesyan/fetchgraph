from __future__ import annotations

import sqlite3

from llm.services.cache import SQLiteCache


def test_sqlite_cache_set_get_and_stats(tmp_path):
    db = tmp_path / "cache.sqlite"
    c = SQLiteCache(path=str(db), ttl_seconds=0, enabled=True)

    # Miss
    assert c.get("missing") is None

    # Set + hit
    c.set("k1", {"a": 1})
    assert c.get("k1") == {"a": 1}

    stats = c.stats()
    assert stats.hits == 1
    assert stats.misses == 1
    assert stats.sets == 1
    assert stats.expired == 0


def test_sqlite_cache_ttl_expiration(tmp_path):
    db = tmp_path / "cache.sqlite"
    c = SQLiteCache(path=str(db), ttl_seconds=10, enabled=True)

    c.set("k1", "v1")

    # Force-expire by moving timestamp into the past.
    with sqlite3.connect(str(db)) as conn:
        conn.execute("UPDATE cache SET ts=? WHERE key=?", (0, "k1"))
        conn.commit()

    assert c.get("k1") is None

    stats = c.stats()
    assert stats.expired == 1


def test_sqlite_cache_corrupted_entry_is_deleted(tmp_path):
    db = tmp_path / "cache.sqlite"
    c = SQLiteCache(path=str(db), ttl_seconds=0, enabled=True)

    # Insert a bad blob directly.
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO cache(key, value, ts) VALUES(?, ?, ?)",
            ("bad", b"not-a-pickle", 123),
        )
        conn.commit()

    assert c.get("bad") is None

    # Ensure it was deleted.
    with sqlite3.connect(str(db)) as conn:
        row = conn.execute("SELECT key FROM cache WHERE key=?", ("bad",)).fetchone()
    assert row is None