import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text, UniqueConstraint, Uuid, func
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
    text: Mapped[str] = mapped_column(Text)
    client_msg_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sender: Mapped[User | None] = relationship(lazy="raise")
