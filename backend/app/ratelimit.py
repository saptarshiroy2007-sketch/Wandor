"""Small in-memory rate limiter for the endpoints that call Razorpay.

Why it exists: create-order and subscribe each make a paid-API call to Razorpay and
create rows/orders on their side. A stuck button, a buggy client loop or a hostile
logged-in user could hammer them. This caps attempts per person per minute.

Scope, stated plainly:
- Keyed by the caller's verified JWT subject (their user id), falling back to the client
  IP only when there is no valid token. Per-user, not per-IP, so a whole coaching centre
  behind one router IP is never throttled as a group.
- State is in process memory. With N backend workers/instances each has its own counter,
  so the effective cap is up to N x the configured limit. Fine for a single instance;
  move the counters to Redis before running many.
- Sliding window. Old hits are dropped as they age out.

Settings (database.py): RATE_LIMIT_ENABLED kill switch, plus one per-minute limit per
bucket. Limits are read at request time, so they can be tuned without code changes.
"""
import threading
import time
from collections import deque

from fastapi import HTTPException, Request

from .auth import _decode
from .database import settings

_WINDOW_SECONDS = 60
_MAX_KEYS = 20000  # hard bound on memory: past this, fully-expired keys are purged

_lock = threading.Lock()
_hits: dict[str, deque] = {}


def _identity(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        try:
            return f"u:{_decode(header[7:].strip())['sub']}"
        except HTTPException:
            pass  # bad/expired token: the route's own auth will reject it; limit by IP meanwhile
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"


def _purge(now: float) -> None:
    for key in [k for k, d in _hits.items() if not d or now - d[-1] >= _WINDOW_SECONDS]:
        del _hits[key]


def reset() -> None:
    """Clear all counters (used by tests)."""
    with _lock:
        _hits.clear()


def rate_limit(bucket: str, limit_setting: str):
    """FastAPI dependency factory. `limit_setting` names the Settings field holding the
    allowed hits per minute, e.g. rate_limit("create-order", "rate_limit_payment_per_min").
    Usage: @router.post(..., dependencies=[Depends(rate_limit(...))])"""

    def _dependency(request: Request) -> None:
        if not settings.rate_limit_enabled:
            return
        limit = int(getattr(settings, limit_setting))
        if limit <= 0:
            return
        now = time.monotonic()
        key = f"{bucket}|{_identity(request)}"
        with _lock:
            if len(_hits) > _MAX_KEYS:
                _purge(now)
            hits = _hits.setdefault(key, deque())
            while hits and now - hits[0] >= _WINDOW_SECONDS:
                hits.popleft()
            if len(hits) >= limit:
                retry_after = max(1, int(_WINDOW_SECONDS - (now - hits[0])) + 1)
                raise HTTPException(
                    status_code=429,
                    # plain string: every page already renders err.response.data.detail as text
                    detail="Too many attempts. Please wait a minute and try again.",
                    headers={"Retry-After": str(retry_after)},
                )
            hits.append(now)

    return _dependency
