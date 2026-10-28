from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chat, Message
from app.services.chats import list_user_chats
from app.services.messages import MESSAGE_LOAD_OPTIONS, unread_counts


@dataclass
class ChatSummary:
    chat: Chat
    last_message: Message | None
    unread_count: int

    @property
    def last_activity(self) -> datetime:
        return self.last_message.created_at if self.last_message else self.chat.created_at


async def chat_summaries(session: AsyncSession, user_id: int) -> list[ChatSummary]:
    """The user's chats with last message and unread count, most recently active first."""
    chats = await list_user_chats(session, user_id)
    if not chats:
        return []
    chat_ids = [chat.id for chat in chats]

    last_messages = await session.scalars(
        select(Message)
        .ext(distinct_on(Message.chat_id))
        .where(Message.chat_id.in_(chat_ids))
        .order_by(Message.chat_id, Message.id.desc())
        .options(*MESSAGE_LOAD_OPTIONS)
    )
    last_by_chat = {message.chat_id: message for message in last_messages}
    unread = await unread_counts(session, user_id, chat_ids)

    summaries = [
        ChatSummary(chat, last_by_chat.get(chat.id), unread.get(chat.id, 0)) for chat in chats
    ]
    summaries.sort(key=lambda s: (s.last_activity, s.chat.id), reverse=True)
    return summaries
