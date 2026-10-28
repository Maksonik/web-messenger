"""Events sent to clients, and helpers that publish them to the right users.

Server → client event types:
  auth.ok          {user}                      after a successful handshake
  message.ack      {client_msg_id, message}    to the sending socket: the message is stored
  message.new      {message}                   to every member of the chat
  message.updated  {message}                   edited, deleted or reactions changed
  read.updated     {chat_id, user_id, last_read_message_id}
  chat.updated     {chat_id}                   chat created/renamed/members changed: refetch it
  error            {code, detail, client_msg_id?}
  pong             {}
"""

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatMember, Message
from app.realtime.bus import event_bus
from app.schemas.message import MessageRead


def message_payload(message: Message) -> dict:
    return MessageRead.model_validate(message).model_dump(mode="json")


async def chat_member_ids(session: AsyncSession, chat_id: int) -> list[int]:
    result = await session.scalars(select(ChatMember.user_id).where(ChatMember.chat_id == chat_id))
    return list(result.all())


async def notify_new_message(session: AsyncSession, message: Message) -> None:
    recipients = await chat_member_ids(session, message.chat_id)
    await event_bus.publish(
        recipients, {"type": "message.new", "message": message_payload(message)}
    )


async def notify_message_updated(session: AsyncSession, message: Message) -> None:
    recipients = await chat_member_ids(session, message.chat_id)
    await event_bus.publish(
        recipients, {"type": "message.updated", "message": message_payload(message)}
    )


async def notify_read(session: AsyncSession, chat_id: int, user_id: int, last_read: int) -> None:
    """Other members show read receipts; the reader's other tabs clear their unread badge."""
    recipients = await chat_member_ids(session, chat_id)
    await event_bus.publish(
        recipients,
        {
            "type": "read.updated",
            "chat_id": chat_id,
            "user_id": user_id,
            "last_read_message_id": last_read,
        },
    )


async def notify_chat_updated(
    session: AsyncSession,
    chat_id: int,
    also_notify: Iterable[int] = (),
    *,
    only: Iterable[int] | None = None,
) -> None:
    """Tells current members (plus e.g. a just-removed user) to refetch the chat."""
    if only is not None:
        recipients = list(only)
    else:
        recipients = [*await chat_member_ids(session, chat_id), *also_notify]
    await event_bus.publish(recipients, {"type": "chat.updated", "chat_id": chat_id})
