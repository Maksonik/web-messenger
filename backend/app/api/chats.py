from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser
from app.core.db import SessionDep
from app.models import Chat, ChatMember
from app.schemas.chat import (
    ChatRead,
    ChatUpdate,
    DirectChatCreate,
    GroupChatCreate,
    MemberAdd,
    MemberRead,
)
from app.services import chats as chats_service

router = APIRouter(prefix="/chats", tags=["chats"])


@router.get("", response_model=list[ChatRead])
async def list_chats(session: SessionDep, user: CurrentUser) -> list[Chat]:
    return list(await chats_service.list_user_chats(session, user.id))


@router.post(
    "/direct",
    response_model=ChatRead,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_200_OK: {"description": "The chat already existed"}},
)
async def open_direct_chat(
    data: DirectChatCreate, session: SessionDep, user: CurrentUser, response: Response
) -> Chat:
    chat, created = await chats_service.get_or_create_direct_chat(session, user, data.user_id)
    if not created:
        response.status_code = status.HTTP_200_OK
    return chat


@router.post("/group", response_model=ChatRead, status_code=status.HTTP_201_CREATED)
async def create_group_chat(data: GroupChatCreate, session: SessionDep, user: CurrentUser) -> Chat:
    return await chats_service.create_group_chat(session, user, data.title, data.member_ids)


@router.get("/{chat_id}", response_model=ChatRead)
async def get_chat(chat_id: int, session: SessionDep, user: CurrentUser) -> Chat:
    return await chats_service.get_chat(session, chat_id, user.id)


@router.patch("/{chat_id}", response_model=ChatRead)
async def rename_chat(
    chat_id: int, data: ChatUpdate, session: SessionDep, user: CurrentUser
) -> Chat:
    return await chats_service.rename_group(session, chat_id, user.id, data.title)


@router.post("/{chat_id}/members", response_model=MemberRead, status_code=status.HTTP_201_CREATED)
async def add_member(
    chat_id: int, data: MemberAdd, session: SessionDep, user: CurrentUser
) -> ChatMember:
    return await chats_service.add_member(session, chat_id, user.id, data.user_id)


@router.delete("/{chat_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(chat_id: int, user_id: int, session: SessionDep, user: CurrentUser) -> None:
    await chats_service.remove_member(session, chat_id, user.id, user_id)
