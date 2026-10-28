import uuid

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.db import escape_like
from app.models import Message, User
from app.services.chats import require_membership


async def send_message(
    session: AsyncSession,
    chat_id: int,
    sender: User,
    text: str,
    client_msg_id: uuid.UUID | None = None,
) -> tuple[Message, bool]:
    """Stores a message; returns (message, created). Idempotent per client_msg_id."""
    await require_membership(session, chat_id, sender.id)

    if client_msg_id is not None:
        existing = await _find_by_client_id(session, chat_id, sender.id, client_msg_id)
        if existing is not None:
            return existing, False

    message = Message(chat_id=chat_id, sender=sender, text=text, client_msg_id=client_msg_id)
    session.add(message)
    try:
        await session.commit()
    except IntegrityError:
        # A concurrent retry with the same client_msg_id won the race.
        await session.rollback()
        existing = await _find_by_client_id(session, chat_id, sender.id, client_msg_id)
        if existing is None:
            raise
        return existing, False
    return message, True


async def list_messages(
    session: AsyncSession, chat_id: int, user_id: int, *, before_id: int | None, limit: int
) -> tuple[list[Message], bool]:
    """A page of history older than before_id, in chronological order; returns (items, has_more)."""
    await require_membership(session, chat_id, user_id)
    items, has_more = await _page(_chat_messages(chat_id, before_id), limit, session)
    return items[::-1], has_more


async def search_messages(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    query: str,
    *,
    before_id: int | None,
    limit: int,
) -> tuple[list[Message], bool]:
    """Case-insensitive substring search within a chat, newest first; returns (items, has_more)."""
    await require_membership(session, chat_id, user_id)
    stmt = _chat_messages(chat_id, before_id).where(
        Message.text.ilike(f"%{escape_like(query)}%", escape="\\")
    )
    return await _page(stmt, limit, session)


def _chat_messages(chat_id: int, before_id: int | None) -> Select[tuple[Message]]:
    stmt = (
        select(Message)
        .where(Message.chat_id == chat_id)
        .options(joinedload(Message.sender))
        .order_by(Message.id.desc())
    )
    if before_id is not None:
        stmt = stmt.where(Message.id < before_id)
    return stmt


async def _page(
    stmt: Select[tuple[Message]], limit: int, session: AsyncSession
) -> tuple[list[Message], bool]:
    # Fetch one extra row to know whether there is another page.
    items = list((await session.scalars(stmt.limit(limit + 1))).all())
    return items[:limit], len(items) > limit


async def _find_by_client_id(
    session: AsyncSession, chat_id: int, sender_id: int, client_msg_id: uuid.UUID | None
) -> Message | None:
    return await session.scalar(
        select(Message)
        .where(
            Message.chat_id == chat_id,
            Message.sender_id == sender_id,
            Message.client_msg_id == client_msg_id,
        )
        .options(joinedload(Message.sender))
    )
