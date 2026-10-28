from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser
from app.core.db import SessionDep
from app.models import Message
from app.schemas.message import MessageCreate, MessagePage, MessageRead
from app.services import messages as messages_service

router = APIRouter(prefix="/chats/{chat_id}/messages", tags=["messages"])

PageLimit = Annotated[int, Query(ge=1, le=100)]
BeforeId = Annotated[int | None, Query(description="Return messages with id < before_id")]


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
    chat_id: int, data: MessageCreate, session: SessionDep, user: CurrentUser, response: Response
) -> Message:
    message, created = await messages_service.send_message(
        session, chat_id, user, data.text, data.client_msg_id
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return message
