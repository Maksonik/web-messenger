import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from urllib.parse import quote

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
    field_validator,
    model_validator,
)

from app.core.security import sign_attachment
from app.schemas.user import UserRead

MAX_TEXT_LENGTH = 4000
MAX_ATTACHMENTS = 10

MessageText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TEXT_LENGTH)
]
# Text that may be empty when the message carries attachments.
OptionalMessageText = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=MAX_TEXT_LENGTH)
]
AttachmentIds = Annotated[list[int], Field(max_length=MAX_ATTACHMENTS)]

ALLOWED_REACTIONS = ("👍", "❤️", "😂", "😮", "😢", "🔥")

# Served inline; anything else (including SVG/HTML, which could run scripts) is downloaded.
INLINE_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})

# Links stay valid 7–8 days and are stable within a UTC day, so browsers can cache files.
ATTACHMENT_LINK_DAYS = 8


class MessageCreate(BaseModel):
    text: OptionalMessageText = ""
    # Client-generated id; resending with the same id returns the stored message.
    client_msg_id: uuid.UUID | None = None
    reply_to_id: int | None = None
    attachment_ids: AttachmentIds = []

    @model_validator(mode="after")
    def _not_empty(self) -> "MessageCreate":
        if not self.text and not self.attachment_ids:
            raise ValueError("A message needs text or attachments")
        return self


class MessageUpdate(BaseModel):
    text: OptionalMessageText


class ReadUpdate(BaseModel):
    message_id: int


class AttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    content_type: str
    size: int

    @computed_field
    @property
    def is_image(self) -> bool:
        return self.content_type in INLINE_IMAGE_TYPES

    @computed_field
    @property
    def url(self) -> str:
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        expires = int((today + timedelta(days=ATTACHMENT_LINK_DAYS)).timestamp())
        signature = sign_attachment(self.id, expires)
        name = quote(self.filename, safe="")
        return f"/api/attachments/{self.id}/{name}?expires={expires}&signature={signature}"


class ReactionGroup(BaseModel):
    emoji: str
    count: int
    user_ids: list[int]


class ReplyPreview(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sender: UserRead | None
    text: str
    deleted: bool


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    chat_id: int
    # None when the sender's account was deleted.
    sender: UserRead | None
    text: str
    client_msg_id: uuid.UUID | None
    created_at: datetime
    edited_at: datetime | None
    deleted: bool
    reply_to: ReplyPreview | None
    reactions: list[ReactionGroup]
    attachments: list[AttachmentRead]
    mention_user_ids: list[int]

    @field_validator("reactions", mode="before")
    @classmethod
    def _group_reactions(cls, value: Any) -> Any:
        """ORM rows (one per user and emoji) → one group per emoji, in order of first use."""
        if not value or isinstance(value[0], dict | ReactionGroup):
            return value
        groups: dict[str, list[int]] = {}
        for reaction in value:
            groups.setdefault(reaction.emoji, []).append(reaction.user_id)
        return [
            {"emoji": emoji, "count": len(user_ids), "user_ids": user_ids}
            for emoji, user_ids in groups.items()
        ]


class MessagePage(BaseModel):
    items: list[MessageRead]
    has_more: bool
