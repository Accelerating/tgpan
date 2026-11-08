import time
from collections import Counter
from contextlib import contextmanager
from ipaddress import ip_address, ip_network
from threading import Lock

from fastapi import HTTPException


def client_address(request):
    peer = request.client.host if request.client else "local"
    try:
        address = ip_address(peer)
        networks = [
            ip_network(value.strip(), strict=False)
            for value in request.app.state.settings.trusted_proxies.split(",")
            if value.strip()
        ]
        forwarded = request.headers.get("x-forwarded-for", "")
        chain = [ip_address(value.strip()) for value in forwarded.split(",")] if forwarded else []
    except ValueError:
        return peer
    for candidate in reversed(chain):
        if not any(address in network for network in networks):
            break
        address = candidate
    return str(address)


def take_attempts(db, rules):
    """Reserve attempts atomically; rules contain (key, limit, window_seconds)."""
    now = time.time()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM login_attempts WHERE time<?", (now - 900,))
        for key, limit, window in rules:
            count = conn.execute(
                "SELECT count(*) FROM login_attempts WHERE address=? AND time>?", (key, now - window)
            ).fetchone()[0]
            if count >= limit:
                raise HTTPException(429, "尝试过多，请稍后重试", headers={"Retry-After": str(window)})
        conn.executemany("INSERT INTO login_attempts VALUES (?,?)", [(key, now) for key, _, _ in rules])


class CapacityLimiter:
    """Fail fast rather than queue unbounded requests around slow operations."""

    def __init__(self, total, per_key=1):
        self.total, self.per_key = total, per_key
        self.active = Counter()
        self.lock = Lock()

    @contextmanager
    def acquire(self, key):
        with self.lock:
            if sum(self.active.values()) >= self.total or self.active[key] >= self.per_key:
                raise HTTPException(429, "请求繁忙，请稍后重试", headers={"Retry-After": "3"})
            self.active[key] += 1
        try:
            yield
        finally:
            with self.lock:
                self.active[key] -= 1
                if not self.active[key]:
                    del self.active[key]
