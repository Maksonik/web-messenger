from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status

from app.api.deps import CurrentUser
from app.core.db import SessionDep
from app.core.redis import RedisDep
from app.models import Message
from app.realtime.events import notify_message_updated, notify_new_message
from app.schemas.message import MessageCreate, MessagePage, MessageRead, MessageUpdate
from app.services import messages as messages_service
from app.services.rate_limit import check_send_rate

router = APIRouter(prefix="/chats/{chat_id}/messages", tags=["messages"])

PageLimit = Annotated[int, Query(ge=1, le=100)]
BeforeId = Annotated[int | None, Query(description="Return messages with id < before_id")]
Emoji = Annotated[str, Path(max_length=16)]


@router.get("")
async def list_messages(
    chat_id: int,
    session: SessionDep,
    user: CurrentUser,
    before_id: BeforeId = None,
    limit: PageLimit = 50,
) -> MessagePage:
    """History, oldest to newest. To load older messages pass before_id = items[0].id."""
    items, has_more = await messages_service.list_messages(
        session, chat_id, user.id, before_id=before_id, limit=limit
    )
    return MessagePage(items=items, has_more=has_more)


@router.get("/search")
async def search_messages(
    chat_id: int,
    session: SessionDep,
    user: CurrentUser,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    before_id: BeforeId = None,
    limit: PageLimit = 20,
) -> MessagePage:
    """Matches, newest first. For the next page pass before_id = items[-1].id."""
    items, has_more = await messages_service.search_messages(
        session, chat_id, user.id, q, before_id=before_id, limit=limit
    )
    return MessagePage(items=items, has_more=has_more)


@router.post(
    "",
    response_model=MessageRead,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_200_OK: {"description": "Duplicate client_msg_id; existing message"}},
)
async def send_message(
    chat_id: int,
    data: MessageCreate,
    session: SessionDep,
    redis: RedisDep,
    user: CurrentUser,
    response: Response,
) -> Message:
    await check_send_rate(redis, user.id)
    message, created = await messages_service.send_message(
        session,
        chat_id,
        user,
        data.text,
        data.client_msg_id,
        reply_to_id=data.reply_to_id,
        attachment_ids=data.attachment_ids,
    )
    if created:
        await notify_new_message(session, message)
    else:
        response.status_code = status.HTTP_200_OK
    return message


@router.patch("/{message_id}", response_model=MessageRead)
async def edit_message(
    chat_id: int, message_id: int, data: MessageUpdate, session: SessionDep, user: CurrentUser
) -> Message:
    """Author only; sets edited_at."""
    message = await messages_service.edit_message(session, chat_id, message_id, user.id, data.text)
    await notify_message_updated(session, message)
    return message


@router.delete("/{message_id}", response_model=MessageRead)
async def delete_message(
    chat_id: int, message_id: int, session: SessionDep, user: CurrentUser
) -> Message:
    """Author, or a group admin as moderation. The message stays as a 'deleted' placeholder."""
    message = await messages_service.delete_message(session, chat_id, message_id, user.id)
    await notify_message_updated(session, message)
    return message


@router.put("/{message_id}/reactions/{emoji}", response_model=MessageRead)
async def add_reaction(
    chat_id: int, message_id: int, emoji: Emoji, session: SessionDep, user: CurrentUser
) -> Message:
    message = await messages_service.set_reaction(
        session, chat_id, message_id, user.id, emoji, on=True
    )
    await notify_message_updated(session, message)
    return message


@router.delete("/{message_id}/reactions/{emoji}", response_model=MessageRead)
async def remove_reaction(
    chat_id: int, message_id: int, emoji: Emoji, session: SessionDep, user: CurrentUser
) -> Message:
    message = await messages_service.set_reaction(
        session, chat_id, message_id, user.id, emoji, on=False
    )
    await notify_message_updated(session, message)
    return message
