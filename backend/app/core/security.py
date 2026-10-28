import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.core.config import settings

password_hash = PasswordHash.recommended()

# Verified against when the user does not exist, so login timing doesn't reveal valid usernames.
DUMMY_PASSWORD_HASH = password_hash.hash("dummy-password-for-timing")


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def create_access_token(user_id: int) -> tuple[str, int]:
    """Returns the token and its lifetime in seconds."""
    ttl = timedelta(minutes=settings.access_token_ttl_minutes)
    now = datetime.now(UTC)
    payload = {"sub": str(user_id), "type": "access", "iat": now, "exp": now + ttl}
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, int(ttl.total_seconds())


def decode_access_token(token: str) -> int:
    """Returns the user id; raises jwt.InvalidTokenError for any invalid token."""
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["sub", "exp", "type"]},
    )
    if payload["type"] != "access":
        raise jwt.InvalidTokenError("Not an access token")
    try:
        return int(payload["sub"])
    except ValueError as exc:
        raise jwt.InvalidTokenError("Invalid subject") from exc


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def sign_attachment(attachment_id: int, expires: int) -> str:
    message = f"attachment:{attachment_id}:{expires}".encode()
    return hmac.new(settings.jwt_secret.encode(), message, hashlib.sha256).hexdigest()[:32]


def verify_attachment_signature(attachment_id: int, expires: int, signature: str) -> bool:
    if expires < datetime.now(UTC).timestamp():
        return False
    return hmac.compare_digest(sign_attachment(attachment_id, expires), signature)
