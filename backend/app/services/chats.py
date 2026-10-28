from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Chat, ChatMember, ChatType, MemberRole, User
from app.services.errors import ConflictError, ForbiddenError, NotFoundError, ServiceError

_WITH_MEMBERS = selectinload(Chat.members).selectinload(ChatMember.user)


async def list_user_chats(session: AsyncSession, user_id: int) -> Sequence[Chat]:
    result = await session.scalars(
        select(Chat).join(ChatMember).where(ChatMember.user_id == user_id).options(_WITH_MEMBERS)
    )
    return result.all()


async def set_muted(session: AsyncSession, chat_id: int, user_id: int, muted: bool) -> bool:
    """Mute is a per-member flag: muted chats don't raise unread notifications."""
    _, member = await require_membership(session, chat_id, user_id)
    member.muted = muted
    await session.commit()
    return muted


async def get_chat(session: AsyncSession, chat_id: int, user_id: int) -> Chat:
    """Returns the chat with members; non-members get 404 so chat ids don't leak."""
    if await session.get(ChatMember, (chat_id, user_id)) is None:
        raise NotFoundError("Chat not found")
    return await _load_chat(session, chat_id)


async def get_or_create_direct_chat(
    session: AsyncSession, user: User, peer_id: int
) -> tuple[Chat, bool]:
    """Returns (chat, created)."""
    if peer_id == user.id:
        raise ServiceError("Cannot start a direct chat with yourself")
    peer = await session.get(User, peer_id)
    if peer is None:
        raise NotFoundError("User not found")

    key = f"{min(user.id, peer_id)}:{max(user.id, peer_id)}"
    existing_id = await session.scalar(select(Chat.id).where(Chat.direct_key == key))
    if existing_id is not None:
        return await _load_chat(session, existing_id), False

    chat = Chat(type=ChatType.direct, direct_key=key, created_by=user.id)
    chat.members = [ChatMember(user=user), ChatMember(user=peer)]
    session.add(chat)
    try:
        await session.commit()
    except IntegrityError:
        # The peer created the same chat concurrently.
        await session.rollback()
        existing_id = await session.scalar(select(Chat.id).where(Chat.direct_key == key))
        if existing_id is None:
            raise
        return await _load_chat(session, existing_id), False
    return await _load_chat(session, chat.id), True


async def create_group_chat(
    session: AsyncSession, creator: User, title: str, member_ids: list[int]
) -> Chat:
    ids = set(member_ids) - {creator.id}
    users = (await session.scalars(select(User).where(User.id.in_(ids)))).all() if ids else []
    missing = ids - {u.id for u in users}
    if missing:
        raise NotFoundError(f"Users not found: {sorted(missing)}")

    chat = Chat(type=ChatType.group, title=title, created_by=creator.id)
    chat.members = [ChatMember(user=creator, role=MemberRole.admin)] + [
        ChatMember(user=u) for u in users
    ]
    session.add(chat)
    await session.commit()
    return await _load_chat(session, chat.id)


async def rename_group(session: AsyncSession, chat_id: int, actor_id: int, title: str) -> Chat:
    chat = await _require_group_admin(session, chat_id, actor_id)
    chat.title = title
    await session.commit()
    return await _load_chat(session, chat_id)


async def add_member(
    session: AsyncSession, chat_id: int, actor_id: int, user_id: int
) -> ChatMember:
    await _require_group_admin(session, chat_id, actor_id)
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    if await session.get(ChatMember, (chat_id, user_id)) is not None:
        raise ConflictError("User is already a member")

    member = ChatMember(chat_id=chat_id, user=user)
    session.add(member)
    await session.commit()
    return member


async def remove_member(session: AsyncSession, chat_id: int, actor_id: int, user_id: int) -> None:
    """Admins can remove anyone; any member can remove themselves (leave)."""
    if user_id == actor_id:
        await require_membership(session, chat_id, actor_id, group_only=True)
    else:
        await _require_group_admin(session, chat_id, actor_id)

    member = await session.get(ChatMember, (chat_id, user_id))
    if member is None:
        raise NotFoundError("User is not a member of this chat")
    if member.role == MemberRole.admin:
        admins = await session.scalar(
            select(func.count())
            .select_from(ChatMember)
            .where(ChatMember.chat_id == chat_id, ChatMember.role == MemberRole.admin)
        )
        if admins == 1:
            raise ConflictError("The last admin cannot leave the chat")

    await session.delete(member)
    await session.commit()


async def _load_chat(session: AsyncSession, chat_id: int) -> Chat:
    return await session.scalar(
        select(Chat)
        .where(Chat.id == chat_id)
        .options(_WITH_MEMBERS)
        .execution_options(populate_existing=True)
    )


async def require_membership(
    session: AsyncSession, chat_id: int, user_id: int, *, group_only: bool = False
) -> tuple[Chat, ChatMember]:
    member = await session.get(ChatMember, (chat_id, user_id))
    chat = await session.get(Chat, chat_id) if member else None
    if member is None or chat is None:
        raise NotFoundError("Chat not found")
    if group_only and chat.type != ChatType.group:
        raise ServiceError("This action is only available in group chats")
    return chat, member


async def _require_group_admin(session: AsyncSession, chat_id: int, user_id: int) -> Chat:
    chat, member = await require_membership(session, chat_id, user_id, group_only=True)
    if member.role != MemberRole.admin:
        raise ForbiddenError("Only chat admins can do this")
    return chat
