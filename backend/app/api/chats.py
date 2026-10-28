from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser
from app.core.db import SessionDep
from app.models import ChatMember
from app.realtime.events import notify_chat_updated, notify_read
from app.schemas.chat import (
    ChatRead,
    ChatUpdate,
    DirectChatCreate,
    GroupChatCreate,
    MemberAdd,
    MemberRead,
    MuteUpdate,
)
from app.schemas.message import ReadUpdate
from app.services import chats as chats_service
from app.services import messages as messages_service
from app.services.chat_list import chat_summaries

router = APIRouter(prefix="/chats", tags=["chats"])


@router.get("")
async def list_chats(session: SessionDep, user: CurrentUser) -> list[ChatRead]:
    """The user's chats with last message and unread count, most recently active first."""
    return [
        ChatRead.for_viewer(
            s.chat, user.id, last_message=s.last_message, unread_count=s.unread_count
        )
        for s in await chat_summaries(session, user.id)
    ]


@router.post(
    "/direct",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_200_OK: {"description": "The chat already existed"}},
)
async def open_direct_chat(
    data: DirectChatCreate, session: SessionDep, user: CurrentUser, response: Response
) -> ChatRead:
    chat, created = await chats_service.get_or_create_direct_chat(session, user, data.user_id)
    if created:
        await notify_chat_updated(session, chat.id)
    else:
        response.status_code = status.HTTP_200_OK
    return ChatRead.for_viewer(chat, user.id)


@router.post("/group", status_code=status.HTTP_201_CREATED)
async def create_group_chat(
    data: GroupChatCreate, session: SessionDep, user: CurrentUser
) -> ChatRead:
    chat = await chats_service.create_group_chat(session, user, data.title, data.member_ids)
    await notify_chat_updated(session, chat.id)
    return ChatRead.for_viewer(chat, user.id)


@router.get("/{chat_id}")
async def get_chat(chat_id: int, session: SessionDep, user: CurrentUser) -> ChatRead:
    return ChatRead.for_viewer(await chats_service.get_chat(session, chat_id, user.id), user.id)


@router.patch("/{chat_id}")
async def rename_chat(
    chat_id: int, data: ChatUpdate, session: SessionDep, user: CurrentUser
) -> ChatRead:
    chat = await chats_service.rename_group(session, chat_id, user.id, data.title)
    await notify_chat_updated(session, chat_id)
    return ChatRead.for_viewer(chat, user.id)


@router.post("/{chat_id}/members", response_model=MemberRead, status_code=status.HTTP_201_CREATED)
async def add_member(
    chat_id: int, data: MemberAdd, session: SessionDep, user: CurrentUser
) -> ChatMember:
    member = await chats_service.add_member(session, chat_id, user.id, data.user_id)
    await notify_chat_updated(session, chat_id)
    return member


@router.delete("/{chat_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(chat_id: int, user_id: int, session: SessionDep, user: CurrentUser) -> None:
    await chats_service.remove_member(session, chat_id, user.id, user_id)
    await notify_chat_updated(session, chat_id, also_notify=[user_id])


@router.post("/{chat_id}/read")
async def mark_read(
    chat_id: int, data: ReadUpdate, session: SessionDep, user: CurrentUser
) -> dict[str, int]:
    """Marks everything up to message_id as read; the marker never moves back."""
    last_read, changed = await messages_service.mark_read(
        session, chat_id, user.id, data.message_id
    )
    if changed:
        await notify_read(session, chat_id, user.id, last_read)
    return {"last_read_message_id": last_read}


@router.put("/{chat_id}/mute")
async def set_muted(
    chat_id: int, data: MuteUpdate, session: SessionDep, user: CurrentUser
) -> dict[str, bool]:
    muted = await chats_service.set_muted(session, chat_id, user.id, data.muted)
    # Only this user's other tabs care.
    await notify_chat_updated(session, chat_id, only=[user.id])
    return {"muted": muted}
