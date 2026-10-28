import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.db import escape_like
from app.models import (
    Attachment,
    ChatMember,
    ChatType,
    MemberRole,
    Message,
    MessageMention,
    MessageReaction,
    User,
)
from app.schemas.message import ALLOWED_REACTIONS
from app.services import storage
from app.services.chats import require_membership
from app.services.errors import ForbiddenError, NotFoundError, ServiceError

# Everything MessageRead needs, so serializing never triggers a lazy load.
MESSAGE_LOAD_OPTIONS = (
    joinedload(Message.sender),
    selectinload(Message.reply_to).joinedload(Message.sender),
    selectinload(Message.reactions),
    selectinload(Message.mentions),
    selectinload(Message.attachments),
)

MENTION_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9_]{3,32})")


async def send_message(
    session: AsyncSession,
    chat_id: int,
    sender: User,
    text: str,
    client_msg_id: uuid.UUID | None = None,
    *,
    reply_to_id: int | None = None,
    attachment_ids: Sequence[int] = (),
) -> tuple[Message, bool]:
    """Stores a message; returns (message, created). Idempotent per client_msg_id."""
    await require_membership(session, chat_id, sender.id)

    if client_msg_id is not None:
        existing = await _find_by_client_id(session, chat_id, sender.id, client_msg_id)
        if existing is not None:
            return existing, False

    if reply_to_id is not None:
        await _get_chat_message(session, chat_id, reply_to_id)
    attachments = await _claim_attachments(session, chat_id, sender.id, attachment_ids)

    message = Message(
        chat_id=chat_id,
        sender=sender,
        text=text,
        client_msg_id=client_msg_id,
        reply_to_id=reply_to_id,
        attachments=attachments,
        mentions=await _mentions(session, chat_id, sender.id, text),
    )
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
    return await load_message(session, message.id), True


async def edit_message(
    session: AsyncSession, chat_id: int, message_id: int, user_id: int, text: str
) -> Message:
    """Only the author can edit; the message gets an edited_at mark."""
    await require_membership(session, chat_id, user_id)
    message = await _get_chat_message(session, chat_id, message_id)
    if message.sender_id != user_id:
        raise ForbiddenError("Only the author can edit a message")
    if message.deleted:
        raise ServiceError("Deleted messages cannot be edited")
    if not text and not message.attachments:
        raise ServiceError("A message needs text or attachments")

    message.text = text
    message.edited_at = datetime.now(UTC)
    message.mentions = await _mentions(session, chat_id, user_id, text)
    await session.commit()
    return await load_message(session, message_id)


async def delete_message(
    session: AsyncSession, chat_id: int, message_id: int, user_id: int
) -> Message:
    """The author, or an admin of a group (moderation), can delete. Leaves a placeholder."""
    chat, member = await require_membership(session, chat_id, user_id)
    message = await _get_chat_message(session, chat_id, message_id)
    is_moderator = chat.type == ChatType.group and member.role == MemberRole.admin
    if message.sender_id != user_id and not is_moderator:
        raise ForbiddenError("You can only delete your own messages")
    if message.deleted:
        return message

    storage_keys = [attachment.storage_key for attachment in message.attachments]
    for attachment in message.attachments:
        await session.delete(attachment)
    message.text = ""
    message.deleted_at = datetime.now(UTC)
    message.reactions.clear()
    message.mentions.clear()
    await session.commit()
    storage.remove_files(storage_keys)
    return await load_message(session, message_id)


async def set_reaction(
    session: AsyncSession, chat_id: int, message_id: int, user_id: int, emoji: str, *, on: bool
) -> Message:
    """Adds (on=True) or removes a reaction; both are idempotent."""
    if emoji not in ALLOWED_REACTIONS:
        raise ServiceError(f"Unsupported reaction; allowed: {' '.join(ALLOWED_REACTIONS)}")
    await require_membership(session, chat_id, user_id)
    message = await _get_chat_message(session, chat_id, message_id)
    if message.deleted:
        raise ServiceError("Cannot react to a deleted message")

    existing = await session.get(MessageReaction, (message_id, user_id, emoji))
    if on and existing is None:
        session.add(MessageReaction(message_id=message_id, user_id=user_id, emoji=emoji))
    elif not on and existing is not None:
        await session.delete(existing)
    await session.commit()
    return await load_message(session, message_id)


async def mark_read(
    session: AsyncSession, chat_id: int, user_id: int, message_id: int
) -> tuple[int, bool]:
    """Moves the read marker forward (never back); returns (last_read_message_id, changed)."""
    _, member = await require_membership(session, chat_id, user_id)
    await _get_chat_message(session, chat_id, message_id)
    current = member.last_read_message_id or 0
    if message_id <= current:
        return current, False
    member.last_read_message_id = message_id
    await session.commit()
    return message_id, True


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
        Message.text.ilike(f"%{escape_like(query)}%", escape="\\"),
        Message.deleted_at.is_(None),
    )
    return await _page(stmt, limit, session)


async def load_message(session: AsyncSession, message_id: int) -> Message:
    message = await session.scalar(
        select(Message)
        .where(Message.id == message_id)
        .options(*MESSAGE_LOAD_OPTIONS)
        .execution_options(populate_existing=True)
    )
    if message is None:
        raise NotFoundError("Message not found")
    return message


async def unread_counts(
    session: AsyncSession, user_id: int, chat_ids: Sequence[int]
) -> dict[int, int]:
    """Messages from others newer than the user's read marker, per chat."""
    result = await session.execute(
        select(Message.chat_id, func.count())
        .join(
            ChatMember,
            (ChatMember.chat_id == Message.chat_id) & (ChatMember.user_id == user_id),
        )
        .where(
            Message.chat_id.in_(chat_ids),
            Message.id > func.coalesce(ChatMember.last_read_message_id, 0),
            Message.sender_id.is_distinct_from(user_id),
            Message.deleted_at.is_(None),
        )
        .group_by(Message.chat_id)
    )
    return {chat_id: count for chat_id, count in result.all()}


def _chat_messages(chat_id: int, before_id: int | None) -> Select[tuple[Message]]:
    stmt = (
        select(Message)
        .where(Message.chat_id == chat_id)
        .options(*MESSAGE_LOAD_OPTIONS)
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


async def _get_chat_message(session: AsyncSession, chat_id: int, message_id: int) -> Message:
    message = await session.scalar(
        select(Message)
        .where(Message.id == message_id, Message.chat_id == chat_id)
        .options(*MESSAGE_LOAD_OPTIONS)
    )
    if message is None:
        raise NotFoundError("Message not found")
    return message


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
        .options(*MESSAGE_LOAD_OPTIONS)
    )


async def _claim_attachments(
    session: AsyncSession, chat_id: int, uploader_id: int, attachment_ids: Sequence[int]
) -> list[Attachment]:
    """Attachments must be the sender's own uploads to this chat, not yet used elsewhere."""
    ids = set(attachment_ids)
    if not ids:
        return []
    attachments = (
        await session.scalars(
            select(Attachment)
            .where(
                Attachment.id.in_(ids),
                Attachment.chat_id == chat_id,
                Attachment.uploader_id == uploader_id,
                Attachment.message_id.is_(None),
            )
            .order_by(Attachment.id)
        )
    ).all()
    if len(attachments) != len(ids):
        raise ServiceError("Unknown or already used attachments")
    return list(attachments)


async def _mentions(
    session: AsyncSession, chat_id: int, author_id: int, text: str
) -> list[MessageMention]:
    """@username mentions of other members of the chat (unknown names are just text)."""
    usernames = {name.lower() for name in MENTION_RE.findall(text)}
    if not usernames:
        return []
    user_ids = await session.scalars(
        select(User.id)
        .join(ChatMember, ChatMember.user_id == User.id)
        .where(
            ChatMember.chat_id == chat_id,
            User.username.in_(usernames),
            User.id != author_id,
        )
    )
    return [MessageMention(user_id=user_id) for user_id in user_ids]
