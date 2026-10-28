import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.models import RefreshToken, User
from app.schemas.auth import RegisterRequest


class UsernameTakenError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class InvalidRefreshTokenError(Exception):
    pass


async def register_user(session: AsyncSession, data: RegisterRequest) -> tuple[User, str]:
    """Creates the user and returns it with a fresh refresh token."""
    # Argon2 is CPU-heavy; keep it off the event loop.
    password_hash = await asyncio.to_thread(hash_password, data.password)
    user = User(
        username=data.username,
        display_name=data.display_name or data.username,
        password_hash=password_hash,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise UsernameTakenError from exc

    refresh_token = _add_refresh_token(session, user.id)
    await session.commit()
    return user, refresh_token


async def login(session: AsyncSession, username: str, password: str) -> tuple[User, str]:
    user = await session.scalar(select(User).where(User.username == username))
    hashed = user.password_hash if user else DUMMY_PASSWORD_HASH
    password_ok = await asyncio.to_thread(verify_password, password, hashed)
    if user is None or not password_ok:
        raise InvalidCredentialsError

    refresh_token = _add_refresh_token(session, user.id)
    await session.commit()
    return user, refresh_token


async def rotate_refresh_token(session: AsyncSession, token: str) -> tuple[User, str]:
    """Revokes the presented token and issues a new one (each token is single-use)."""
    stored = await session.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_refresh_token(token))
        .with_for_update()
    )
    now = datetime.now(UTC)
    if stored is None or stored.revoked_at is not None or stored.expires_at <= now:
        raise InvalidRefreshTokenError

    stored.revoked_at = now
    new_token = _add_refresh_token(session, stored.user_id)
    user = await session.get_one(User, stored.user_id)
    await session.commit()
    return user, new_token


async def revoke_refresh_token(session: AsyncSession, token: str) -> None:
    await session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == hash_refresh_token(token),
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    await session.commit()


def _add_refresh_token(session: AsyncSession, user_id: int) -> str:
    token = generate_refresh_token()
    session.add(
        RefreshToken(
            user_id=user_id,
            token_hash=hash_refresh_token(token),
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    return token
