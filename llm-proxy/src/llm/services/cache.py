# llm/services/cache.py

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import pickle
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

from llm.logging_config import get_logger

logger = get_logger(__name__)


def _stable_json_dumps(obj: Any) -> str:
    """Deterministic JSON encoding (best-effort) for cache keys."""
    return json.dumps(
        obj,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def make_key(*, namespace: str, data: Any) -> str:
    """Build a stable sha256 key for the given namespace + data."""
    blob = _stable_json_dumps({"ns": namespace, "data": data})
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CacheStats:
    hits: int
    misses: int
    sets: int
    expired: int


class SQLiteCache:
    """A small, shared SQLite-backed cache (pickle serialization).

    - Thread-safe for a single-process FastAPI runtime.
    - Optional TTL.
    - Async in-flight de-duplication for identical keys.
    """

    def __init__(
        self,
        *,
        path: str,
        ttl_seconds: int = 0,
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        self.path = path
        self.ttl_seconds = max(int(ttl_seconds or 0), 0)

        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

        self._hits = 0
        self._misses = 0
        self._sets = 0
        self._expired = 0

        # Async de-duplication
        self._inflight: Dict[str, asyncio.Future] = {}
        self._inflight_lock = asyncio.Lock()

        if self.enabled:
            self._init_db()

    def _init_db(self) -> None:
        # Ensure parent directory exists for file-backed caches.
        if self.path != ":memory:":
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
        # timeout + WAL to avoid writer stalls
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        cur = self._conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA busy_timeout=5000;")
        cur.execute(
            "CREATE TABLE IF NOT EXISTS cache("
            "  key TEXT PRIMARY KEY, value BLOB, ts INTEGER"
            ")"
        )

        if self.ttl_seconds > 0:
            cutoff = int(time.time()) - self.ttl_seconds
            cur.execute("DELETE FROM cache WHERE ts < ?", (cutoff,))

        self._conn.commit()
        logger.info("SQLiteCache initialized: path=%s ttl=%s", self.path, self.ttl_seconds)

    def _conn_or_init(self) -> sqlite3.Connection:
        """Return an initialized sqlite connection.

        We keep lazy init (so tests can create disabled caches without touching FS),
        but we also want type-checkers to understand that the connection is not None
        after this call.
        """
        if self._conn is None:
            self._init_db()
        conn = self._conn
        assert conn is not None
        return conn

    def close(self) -> None:
        if self._conn is None:
            return
        with self._lock:
            try:
                self._conn.close()
            finally:
                self._conn = None

    def stats(self) -> CacheStats:
        return CacheStats(
            hits=self._hits,
            misses=self._misses,
            sets=self._sets,
            expired=self._expired,
        )

    def get(self, key: str) -> Any | None:
        if not self.enabled:
            return None

        conn = self._conn_or_init()

        with self._lock:
            row = conn.execute("SELECT value, ts FROM cache WHERE key=?", (key,)).fetchone()

        if not row:
            self._misses += 1
            return None

        blob, ts = row
        if self.ttl_seconds > 0 and (time.time() - ts) > self.ttl_seconds:
            self._expired += 1
            with self._lock:
                conn.execute("DELETE FROM cache WHERE key=?", (key,))
                conn.commit()
            return None

        self._hits += 1
        try:
            return pickle.loads(blob)
        except Exception:  # noqa: BLE001
            # Corrupted entry: delete and treat as miss
            with self._lock:
                conn.execute("DELETE FROM cache WHERE key=?", (key,))
                conn.commit()
            self._misses += 1
            logger.exception("Failed to unpickle cache entry; deleted key=%s", key)
            return None

    def set(self, key: str, value: Any) -> None:
        if not self.enabled:
            return

        conn = self._conn_or_init()

        blob = pickle.dumps(value)
        with self._lock:
            conn.execute(
                "INSERT OR REPLACE INTO cache(key, value, ts) VALUES(?, ?, ?)",
                (key, blob, int(time.time())),
            )
            conn.commit()
        self._sets += 1

    async def aget_or_set(
        self,
        key: str,
        factory: Callable[[], Awaitable[Any]],
        *,
        on_hit: Optional[Callable[[str], None]] = None,
        on_miss: Optional[Callable[[str], None]] = None,
    ) -> Any:
        """Async cache wrapper with in-flight de-duplication."""
        if not self.enabled:
            return await factory()

        cached = self.get(key)
        if cached is not None:
            if on_hit is not None:
                on_hit(key)
            return cached

        if on_miss is not None:
            on_miss(key)

        async with self._inflight_lock:
            existing = self._inflight.get(key)
            if existing is not None:
                return await existing
            loop = asyncio.get_running_loop()
            fut: asyncio.Future = loop.create_future()
            self._inflight[key] = fut

        try:
            value = await factory()
            self.set(key, value)
            fut.set_result(value)
            return value
        except Exception as exc:  # noqa: BLE001
            fut.set_exception(exc)
            raise
        finally:
            async with self._inflight_lock:
                self._inflight.pop(key, None)