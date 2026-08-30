"""Login lockout — in-memory, no Redis needed for a single-process app.

Keyed by username, not by IP: this app sits behind no load balancer/proxy today, so a
per-process client IP is not reliably available, and IP-keying would let one attacker
behind shared NAT (an office, a campus) lock out everyone else on it. The tradeoff is the
reverse — an attacker who knows a valid username can lock that one account out from its
real owner. That's the standard account-lockout tradeoff and still a large improvement over
today's unlimited attempts.
"""
from __future__ import annotations

import threading
import time

_MAX_FAILURES = 5
_WINDOW_SECONDS = 15 * 60
_LOCKOUT_SECONDS = 15 * 60

_lock = threading.Lock()
_failures: dict[str, list[float]] = {}


def is_locked_out(username: str) -> int | None:
    """Returns remaining lockout seconds if locked out, else None."""
    with _lock:
        attempts = _failures.get(username, [])
        if len(attempts) < _MAX_FAILURES:
            return None
        lockout_until = attempts[-1] + _LOCKOUT_SECONDS
        remaining = lockout_until - time.time()
        if remaining <= 0:
            _failures.pop(username, None)
            return None
        return int(remaining)


def record_failure(username: str) -> None:
    now = time.time()
    with _lock:
        attempts = [t for t in _failures.get(username, []) if now - t < _WINDOW_SECONDS]
        attempts.append(now)
        _failures[username] = attempts


def clear_failures(username: str) -> None:
    with _lock:
        _failures.pop(username, None)
