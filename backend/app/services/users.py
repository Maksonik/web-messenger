from collections.abc import Sequence

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import escape_like
from app.models import User


async def search_users(
    session: AsyncSession, query: str, *, exclude_user_id: int, limit: int
) -> Sequence[User]:
    """Prefix search by username or display name, case-insensitive."""
    pattern = f"{escape_like(query)}%"
    result = await session.scalars(
        select(User)
        .where(
            or_(
                User.username.ilike(pattern, escape="\\"),
                User.display_name.ilike(pattern, escape="\\"),
            ),
            User.id != exclude_user_id,
        )
        .order_by(User.username)
        .limit(limit)
    )
    return result.all()
