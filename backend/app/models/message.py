import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.user import User


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        # Cursor pagination: WHERE chat_id = ? AND id < ? ORDER BY id DESC.
        Index("ix_messages_chat_id_id", "chat_id", "id"),
        # Substring search (ILIKE '%q%') via pg_trgm.
        Index(
            "ix_messages_text_trgm",
            "text",
            postgresql_using="gin",
            postgresql_ops={"text": "gin_trgm_ops"},
        ),
        # Retries of the same client message must not create duplicates.
        UniqueConstraint("chat_id", "sender_id", "client_msg_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"))
    sender_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # Empty for attachment-only and deleted messages.
    text: Mapped[str] = mapped_column(Text)
    client_msg_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reply_to_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Soft delete: the row stays so the history keeps a "message deleted" placeholder.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sender: Mapped[User | None] = relationship(lazy="raise")
    reply_to: Mapped["Message | None"] = relationship(remote_side=[id], lazy="raise")
    reactions: Mapped[list["MessageReaction"]] = relationship(
        cascade="all, delete-orphan", lazy="raise", order_by="MessageReaction.created_at"
    )
    mentions: Mapped[list["MessageMention"]] = relationship(
        cascade="all, delete-orphan", lazy="raise"
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="message", lazy="raise", order_by="Attachment.id"
    )

    @property
    def deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def mention_user_ids(self) -> list[int]:
        return [mention.user_id for mention in self.mentions]


class MessageReaction(Base):
    __tablename__ = "message_reactions"

    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    emoji: Mapped[str] = mapped_column(String(16), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MessageMention(Base):
    __tablename__ = "message_mentions"

    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class Attachment(Base):
    """A file on the server's disk. Uploaded first, then linked to a message when it's sent."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"))
    uploader_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    # Random file name inside upload_dir; never derived from user input.
    storage_key: Mapped[str] = mapped_column(String(64), unique=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(127))
    size: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    message: Mapped[Message | None] = relationship(back_populates="attachments", lazy="raise")
