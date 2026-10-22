from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.security import RateLimiter


def request(peer: str, forwarded: str = "") -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers, "client": (peer, 1234)})


def limiter(monkeypatch, trusted_proxy_ips):
    settings = SimpleNamespace(chat_rate_limit_per_minute=1, trusted_proxy_ips=trusted_proxy_ips)
    monkeypatch.setattr("app.security.get_settings", lambda: settings)
    return RateLimiter()


def test_untrusted_forwarded_header_cannot_bypass_rate_limit(monkeypatch):
    rate_limiter = limiter(monkeypatch, [])
    rate_limiter.check(request("198.51.100.10", "203.0.113.1"))
    with pytest.raises(HTTPException) as error:
        rate_limiter.check(request("198.51.100.10", "203.0.113.2"))
    assert error.value.status_code == 429


def test_trusted_proxy_uses_client_added_at_right_edge_not_spoofed_prefix(monkeypatch):
    rate_limiter = limiter(monkeypatch, ["10.0.0.0/8"])
    rate_limiter.check(request("10.0.0.5", "203.0.113.99, 198.51.100.7"))
    with pytest.raises(HTTPException) as error:
        rate_limiter.check(request("10.0.0.5", "192.0.2.55, 198.51.100.7"))
    assert error.value.status_code == 429


def test_trusted_proxy_setting_accepts_explicit_ip_ranges():
    from app.config import Settings

    settings = Settings(trusted_proxy_ips="10.0.0.1, 192.168.0.0/16")
    assert settings.trusted_proxy_ips == ["10.0.0.1/32", "192.168.0.0/16"]
