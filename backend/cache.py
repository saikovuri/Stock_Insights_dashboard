"""Thread-safe TTL cache with request deduplication.

When multiple threads request the same key simultaneously, only ONE
actually calls the fetch function — the rest wait and share the result.
This eliminates duplicate yfinance calls and drastically reduces
Yahoo Finance rate-limit hits.
"""

import time
import threading
from typing import Any, Callable

_store: dict[str, tuple[Any, float]] = {}   # key → (value, expire_at)
_locks: dict[str, threading.Event] = {}     # key → Event (for dedup)
_global_lock = threading.Lock()


def get_or_fetch(key: str, fetch_fn: Callable[[], Any], ttl: int = 300) -> Any:
    """Return cached value if fresh, else call fetch_fn (deduplicated).

    Args:
        key:      Cache key (e.g. "metrics:AAPL")
        fetch_fn: Zero-arg callable that produces the value
        ttl:      Time-to-live in seconds (default 5 min)
    """
    now = time.time()

    # Fast path: cache hit
    with _global_lock:
        if key in _store:
            val, expires = _store[key]
            if now < expires:
                return val

        # Check if another thread is already fetching this key
        if key in _locks:
            event = _locks[key]
        else:
            # We are the first — claim it
            event = threading.Event()
            _locks[key] = event
            event = None  # signal that WE do the fetch

    if event is not None:
        # Another thread is fetching — wait for it (max 30s)
        event.wait(timeout=30)
        with _global_lock:
            if key in _store:
                return _store[key][0]
        # Fallback: other thread failed, we fetch ourselves
        return fetch_fn()

    # We are the fetcher
    try:
        result = fetch_fn()
        with _global_lock:
            _store[key] = (result, now + ttl)
        return result
    finally:
        with _global_lock:
            evt = _locks.pop(key, None)
        if evt is not None:
            evt.set()  # wake up waiting threads


def invalidate(key: str) -> None:
    """Remove a specific key from cache."""
    with _global_lock:
        _store.pop(key, None)


def clear() -> None:
    """Clear the entire cache."""
    with _global_lock:
        _store.clear()


def stats() -> dict:
    """Return cache statistics."""
    now = time.time()
    with _global_lock:
        total = len(_store)
        active = sum(1 for _, (_, exp) in _store.items() if exp > now)
        expired = total - active
        in_flight = len(_locks)
    return {"total_keys": total, "active": active, "expired": expired, "in_flight": in_flight}
