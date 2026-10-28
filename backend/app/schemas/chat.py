from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models import ChatType, MemberRole
from app.schemas.user import UserRead

ChatTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class MemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user: UserRead
    role: MemberRole
    joined_at: datetime


class ChatRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: ChatType
    title: str | None
    created_at: datetime
    members: list[MemberRead]


class DirectChatCreate(BaseModel):
    user_id: int


class GroupChatCreate(BaseModel):
    title: ChatTitle
    member_ids: Annotated[list[int], Field(max_length=200)] = []


class ChatUpdate(BaseModel):
    title: ChatTitle


class MemberAdd(BaseModel):
    user_id: int
