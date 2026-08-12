from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from fastapi import Cookie, Header, HTTPException
from jwt import InvalidTokenError

from app.config import get_settings


def create_token(username: str) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": username,
            "iat": now,
            "exp": now + timedelta(minutes=settings.admin_token_minutes),
            "iss": settings.admin_jwt_issuer,
            "aud": settings.admin_jwt_audience,
            "jti": str(uuid4()),
        },
        settings.session_secret,
        algorithm="HS256",
    )


def require_session(
    authorization: str = Header(default=""),
    truefox_admin_session: str = Cookie(default=""),
) -> str:
    settings = get_settings()
    token = authorization[7:] if authorization.startswith("Bearer ") else truefox_admin_session
    if not settings.session_secret or not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        data = jwt.decode(
            token,
            settings.session_secret,
            algorithms=["HS256"],
            audience=settings.admin_jwt_audience,
            issuer=settings.admin_jwt_issuer,
            options={"require": ["sub", "iat", "exp", "iss", "aud", "jti"]},
        )
        if data.get("sub") != settings.admin_username:
            raise InvalidTokenError("Unexpected administrator")
        return str(data["sub"])
    except (InvalidTokenError, KeyError):
        raise HTTPException(status_code=401, detail="Invalid or expired session") from None
