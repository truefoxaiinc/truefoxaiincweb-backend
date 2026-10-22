import hmac
import ipaddress
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Header, HTTPException, Request, status

from app.admin_auth import require_session
from app.config import get_settings


def require_admin(x_admin_key: str = Header(default="")) -> None:
    expected = get_settings().admin_api_key
    if not expected or not hmac.compare_digest(x_admin_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin API key")


def require_knowledge_admin(
    request: Request,
    authorization: str = Header(default=""),
    x_admin_key: str = Header(default=""),
) -> str:
    settings = get_settings()
    if x_admin_key and settings.admin_api_key and hmac.compare_digest(x_admin_key, settings.admin_api_key):
        return "api-key"
    return require_session(authorization, request.cookies.get("truefox_admin_session", ""))


class RateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, request: Request) -> None:
        settings = get_settings()
        key = self.client_ip(request, settings.trusted_proxy_ips)
        with self._lock:
            now = time.monotonic()
            events = self._events[key]
            while events and events[0] <= now - 60:
                events.popleft()
            if len(events) >= settings.chat_rate_limit_per_minute:
                raise HTTPException(status_code=429, detail="Too many chat requests. Please try again shortly.")
            events.append(now)

    @staticmethod
    def client_ip(request: Request, trusted_proxy_ranges: list[str]) -> str:
        peer = request.client.host if request.client else "unknown"
        try:
            peer_ip = ipaddress.ip_address(peer)
        except ValueError:
            return peer
        networks = [ipaddress.ip_network(item) for item in trusted_proxy_ranges]
        if not any(peer_ip in network for network in networks):
            return str(peer_ip)

        forwarded = request.headers.get("x-forwarded-for", "")
        candidates: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
        for value in forwarded.split(","):
            try:
                candidates.append(ipaddress.ip_address(value.strip()))
            except ValueError:
                continue
        for candidate in reversed(candidates):
            if not any(candidate in network for network in networks):
                return str(candidate)
        return str(peer_ip)


chat_rate_limiter = RateLimiter()


def enforce_chat_rate_limit(request: Request) -> None:
    chat_rate_limiter.check(request)
