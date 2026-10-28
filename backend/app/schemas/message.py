import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.schemas.user import UserRead

MessageText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]


class MessageCreate(BaseModel):
    text: MessageText
    # Client-generated id; resending with the same id returns the stored message.
    client_msg_id: uuid.UUID | None = None


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    chat_id: int
    # None when the sender's account was deleted.
    sender: UserRead | None
    text: str
    client_msg_id: uuid.UUID | None
    created_at: datetime


class MessagePage(BaseModel):
    items: list[MessageRead]
    has_more: bool
