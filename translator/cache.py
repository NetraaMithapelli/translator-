"""
cache.py
--------
Minimal in-memory TTL cache for (text, target_language) -> translation.

Why this design:
Compliance vocabulary repeats a lot ("NON_COMPLIANT", common rule
descriptions, boilerplate recommendations), so caching avoids paying
provider latency twice for the same string. The task explicitly says
not to over-engineer this ("do not introduce a complicated distributed
caching system unless necessary"), so this is a plain dict guarded by a
lock, good enough for a single backend process.

Scaling path (documented, not built): swap this class's body for a Redis
client (SETEX / GET) behind the same get/set method signatures, and every
caller (translator_service) keeps working unchanged -- that's the whole
point of exposing get/set as the only two methods.
"""

import time
import threading
import hashlib
from typing import Optional


class TranslationCache:
    def __init__(self, ttl_seconds: int = 3600):
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(text: str, target_language: str) -> str:
        # Hash to keep keys short/uniform regardless of source text length.
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"{target_language}:{digest}"

    def get(self, text: str, target_language: str) -> Optional[str]:
        key = self._key(text, target_language)
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at < time.time():
                del self._store[key]
                return None
            return value

    def set(self, text: str, target_language: str, translated: str) -> None:
        key = self._key(text, target_language)
        with self._lock:
            self._store[key] = (translated, time.time() + self._ttl)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
