import hmac
import time
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Request, status

from app.config import get_settings


def require_admin(x_admin_key: str = Header(default="")) -> None:
    expected = get_settings().admin_api_key
    if not expected or not hmac.compare_digest(x_admin_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin API key")


class RateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, request: Request) -> None:
        settings = get_settings()
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        key = forwarded or (request.client.host if request.client else "unknown")
        now = time.monotonic()
        events = self._events[key]
        while events and events[0] <= now - 60:
            events.popleft()
        if len(events) >= settings.chat_rate_limit_per_minute:
            raise HTTPException(status_code=429, detail="Too many chat requests. Please try again shortly.")
        events.append(now)


chat_rate_limiter = RateLimiter()


def enforce_chat_rate_limit(request: Request) -> None:
    chat_rate_limiter.check(request)
