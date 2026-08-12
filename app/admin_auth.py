import base64
import hashlib
import hmac
import json
import time

from fastapi import Cookie, Header, HTTPException

from app.config import get_settings


def create_token(username: str) -> str:
    settings = get_settings()
    payload = base64.urlsafe_b64encode(json.dumps({"sub": username, "exp": int(time.time()) + settings.admin_token_minutes * 60}, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(settings.session_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def require_session(
    authorization: str = Header(default=""),
    truefox_admin_session: str = Cookie(default=""),
) -> str:
    settings = get_settings()
    token = authorization[7:] if authorization.startswith("Bearer ") else truefox_admin_session
    if not settings.session_secret or not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        payload, supplied = token.rsplit(".", 1)
        expected = hmac.new(settings.session_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(supplied, expected): raise ValueError
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if data.get("exp", 0) <= time.time() or data.get("sub") != settings.admin_username: raise ValueError
        return str(data["sub"])
    except (ValueError, KeyError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="Invalid or expired session") from None
