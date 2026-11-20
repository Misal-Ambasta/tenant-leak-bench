"""Async TTL cache with single-flight loading."""

import asyncio
from collections.abc import Awaitable, Callable, Hashable
from dataclasses import dataclass
from typing import Generic, TypeVar

from .clock import Clock

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


@dataclass(frozen=True)
class _Entry(Generic[V]):
    value: V
    expires_at: float


class TtlCache(Generic[K, V]):
    """Caches loader results per key for ``ttl_seconds``.

    Concurrent misses for the same key share a single in-flight load.
    """

    def __init__(self, clock: Clock, ttl_seconds: float) -> None:
        self._clock = clock
        self._ttl_seconds = ttl_seconds
        self._entries: dict[K, _Entry[V]] = {}
        self._inflight: dict[K, asyncio.Task[V]] = {}
        self._generations: dict[K, int] = {}

    async def get_or_load(self, key: K, loader: Callable[[], Awaitable[V]]) -> V:
        entry = self._entries.get(key)
        if entry is not None and self._clock.now() < entry.expires_at:
            return entry.value
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.ensure_future(self._load(key, loader))
            self._inflight[key] = task
        return await asyncio.shield(task)

    def invalidate(self, key: K) -> None:
        self._entries.pop(key, None)
        self._inflight.pop(key, None)
        self._generations[key] = self._generations.get(key, 0) + 1

    async def _load(self, key: K, loader: Callable[[], Awaitable[V]]) -> V:
        generation = self._generations.get(key, 0)
        try:
            value = await loader()
        finally:
            if self._inflight.get(key) is asyncio.current_task():
                del self._inflight[key]
        if self._generations.get(key, 0) == generation:
            self._entries[key] = _Entry(value, self._clock.now() + self._ttl_seconds)
        return value
