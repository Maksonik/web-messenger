from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models import Chat, ChatType, MemberRole, Message
from app.schemas.message import MessageRead
from app.schemas.user import UserRead

ChatTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class MemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user: UserRead
    role: MemberRole
    joined_at: datetime
    # For read receipts: messages up to this id were seen by this member.
    last_read_message_id: int | None


class ChatRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: ChatType
    title: str | None
    created_at: datetime
    members: list[MemberRead]
    # The fields below are specific to the requesting user.
    muted: bool = False
    unread_count: int = 0
    last_message: MessageRead | None = None

    @classmethod
    def for_viewer(
        cls,
        chat: Chat,
        viewer_id: int,
        *,
        last_message: Message | None = None,
        unread_count: int = 0,
    ) -> "ChatRead":
        muted = any(m.user_id == viewer_id and m.muted for m in chat.members)
        return cls.model_validate(chat).model_copy(
            update={
                "muted": muted,
                "unread_count": unread_count,
                "last_message": MessageRead.model_validate(last_message) if last_message else None,
            }
        )


class DirectChatCreate(BaseModel):
    user_id: int


class GroupChatCreate(BaseModel):
    title: ChatTitle
    member_ids: Annotated[list[int], Field(max_length=200)] = []


class ChatUpdate(BaseModel):
    title: ChatTitle


class MemberAdd(BaseModel):
    user_id: int


class MuteUpdate(BaseModel):
    muted: bool
