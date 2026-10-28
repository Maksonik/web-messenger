from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String, false, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.user import User


class ChatType(StrEnum):
    direct = "direct"
    group = "group"


class MemberRole(StrEnum):
    admin = "admin"
    member = "member"


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[ChatType] = mapped_column(
        Enum(ChatType, name="chat_type", native_enum=False, create_constraint=True, length=16)
    )
    title: Mapped[str | None] = mapped_column(String(100))
    # "<smaller user id>:<larger user id>" for direct chats; guarantees one chat per pair.
    direct_key: Mapped[str | None] = mapped_column(String(41), unique=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    members: Mapped[list["ChatMember"]] = relationship(
        back_populates="chat",
        cascade="all, delete-orphan",
        order_by=lambda: [ChatMember.joined_at, ChatMember.user_id],
        lazy="raise",
    )


class ChatMember(Base):
    __tablename__ = "chat_members"

    chat_id: Mapped[int] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[MemberRole] = mapped_column(
        Enum(MemberRole, name="member_role", native_enum=False, create_constraint=True, length=16),
        default=MemberRole.member,
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Read receipts: everything up to this message id counts as read by this member.
    last_read_message_id: Mapped[int | None] = mapped_column(BigInteger)
    muted: Mapped[bool] = mapped_column(default=False, server_default=false())

    chat: Mapped[Chat] = relationship(back_populates="members", lazy="raise")
    user: Mapped[User] = relationship(lazy="raise")
