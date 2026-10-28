"""Fills the database with demo users and conversations for showing the app.

    python -m app.scripts.seed_demo            # only into an empty database
    python -m app.scripts.seed_demo --reset    # wipes ALL data (and uploaded files) first

In Docker: docker compose exec backend python -m app.scripts.seed_demo --reset
"""

import argparse
import asyncio
import io
import struct
import zlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import Base, SessionFactory, engine
from app.core.security import hash_password
from app.models import (
    Attachment,
    Chat,
    ChatMember,
    ChatType,
    MemberRole,
    Message,
    MessageMention,
    MessageReaction,
    User,
)
from app.services import storage

DEMO_PASSWORD = "demo-password"

USERS = {
    "alice": "Алиса Смирнова",
    "bob": "Борис Иванов",
    "kate": "Катя Петрова",
    "dima": "Дима Козлов",
}


def _gradient_png(width: int = 480, height: int = 300) -> bytes:
    """A small PNG "screenshot mockup", generated so the repo needs no binary assets."""
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            header = y < 40
            rows += bytes((59, 130, 246) if header else (230 - x // 8, 236 - y // 10, 245))

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows)))
        + chunk(b"IEND", b"")
    )


async def _attach(
    session: AsyncSession, chat: Chat, uploader: User, name: str, content_type: str, data: bytes
) -> Attachment:
    key = storage.new_key()
    await storage.save(key, io.BytesIO(data))
    attachment = Attachment(
        chat_id=chat.id,
        uploader_id=uploader.id,
        storage_key=key,
        filename=name,
        content_type=content_type,
        size=len(data),
    )
    session.add(attachment)
    return attachment


async def seed(session: AsyncSession) -> None:
    password_hash = hash_password(DEMO_PASSWORD)
    users = {
        username: User(username=username, display_name=name, password_hash=password_hash)
        for username, name in USERS.items()
    }
    session.add_all(users.values())
    await session.flush()
    alice, bob, kate, dima = (users[u] for u in USERS)

    def group(title: str, admin: User, *members: User) -> Chat:
        chat = Chat(type=ChatType.group, title=title, created_by=admin.id)
        chat.members = [ChatMember(user=admin, role=MemberRole.admin)] + [
            ChatMember(user=m) for m in members
        ]
        return chat

    def direct(a: User, b: User) -> Chat:
        key = f"{min(a.id, b.id)}:{max(a.id, b.id)}"
        chat = Chat(type=ChatType.direct, direct_key=key, created_by=a.id)
        chat.members = [ChatMember(user=a), ChatMember(user=b)]
        return chat

    team = group("Команда проекта", alice, bob, kate, dima)
    study = group("Учёба", kate, alice, dima)
    alice_bob = direct(alice, bob)
    alice_kate = direct(alice, kate)
    archive = group("Архив курса", alice, bob, kate)
    session.add_all([team, study, alice_bob, alice_kate, archive])
    await session.flush()

    now = datetime.now(UTC)
    # 18 messages, 4 minutes apart; the newest one is a few minutes old.
    clock = iter(range(20, 0, -1))

    def message(chat: Chat, sender: User, text_: str, **extra) -> Message:
        """Messages get increasing timestamps a few minutes apart, ending now."""
        created = now - timedelta(minutes=next(clock) * 4)
        msg = Message(chat_id=chat.id, sender=sender, text=text_, created_at=created, **extra)
        session.add(msg)
        return msg

    # --- "Архив курса": a long, older history to show "load more" (a page is 50 messages).
    authors = [alice, bob, kate]
    last_archived = None
    for i in range(1, 61):
        last_archived = Message(
            chat_id=archive.id,
            sender=authors[i % len(authors)],
            text=f"Заметка №{i}: материалы занятия {i}",
            created_at=now - timedelta(days=30) + timedelta(hours=11 * i),
        )
        session.add(last_archived)
    await session.flush()

    # --- "Команда проекта": replies, mentions, reactions, an edit and attachments.
    message(team, alice, "Всем привет! Здесь обсуждаем мессенджер 👋")
    kickoff = message(team, alice, "Сегодня нужно доделать WebSocket и фронтенд")
    await session.flush()
    message(team, bob, "Беру WebSocket и Redis pub/sub", reply_to_id=kickoff.id)
    message(team, kate, "Тогда я фронтенд на React + Vite")
    mockup = await _attach(session, team, kate, "maket-chata.png", "image/png", _gradient_png())
    with_image = message(team, kate, "@alice вот макет окна чата, посмотри", attachments=[mockup])
    await session.flush()
    session.add(MessageMention(message_id=with_image.id, user_id=alice.id))
    edited = message(team, dima, "Я напишу тесты на pytest и проверю нагрузку")
    edited.edited_at = edited.created_at + timedelta(minutes=1)
    plan = await _attach(
        session,
        team,
        alice,
        "plan.txt",
        "text/plain",
        "1. MVP\n2. Расширения\n3. Демо-видео\n".encode(),
    )
    message(team, alice, "Обновила план работ", attachments=[plan])
    deleted = message(team, bob, "")
    deleted.deleted_at = deleted.created_at + timedelta(minutes=2)
    ask = message(team, bob, "@kate а статус «прочитано» будет?")
    await session.flush()
    session.add(MessageMention(message_id=ask.id, user_id=kate.id))
    answer = message(team, kate, "Да, по last_read_message_id у участника", reply_to_id=ask.id)
    await session.flush()
    for msg, user, emoji in [
        (kickoff, bob, "👍"),
        (kickoff, kate, "👍"),
        (kickoff, dima, "🔥"),
        (with_image, alice, "❤️"),
        (with_image, bob, "🔥"),
        (answer, bob, "👍"),
    ]:
        session.add(MessageReaction(message_id=msg.id, user_id=user.id, emoji=emoji))
    last_team = message(team, dima, "Тесты зелёные ✅")

    # --- Direct chats.
    message(alice_bob, bob, "Привет! Созвонимся вечером?")
    message(alice_bob, alice, "Давай в 19:00")
    last_ab = message(alice_bob, bob, "Договорились 👍")
    message(alice_kate, kate, "Скинешь конспект по базам данных?")
    last_ak = message(alice_kate, kate, "Особенно про индексы и pg_trgm")

    # --- "Учёба": muted by Alice, so its unread badge stays grey.
    message(study, kate, "Напоминаю: дедлайн по проекту — 28 февраля")
    message(study, dima, "Успеем 💪")
    await session.flush()

    # Read markers: Alice has read her team chat; others are behind, so badges and ✓/✓✓ differ.
    members = {(m.chat_id, m.user_id): m for m in (await session.scalars(select(ChatMember))).all()}
    members[team.id, alice.id].last_read_message_id = last_team.id
    members[team.id, bob.id].last_read_message_id = last_team.id
    members[team.id, kate.id].last_read_message_id = answer.id
    members[alice_bob.id, alice.id].last_read_message_id = last_ab.id - 1
    members[alice_bob.id, bob.id].last_read_message_id = last_ab.id
    members[alice_kate.id, kate.id].last_read_message_id = last_ak.id
    members[study.id, alice.id].muted = True
    members[archive.id, alice.id].last_read_message_id = last_archived.id

    await session.commit()


async def reset(session: AsyncSession) -> None:
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    await session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    await session.commit()
    storage.clear_all()


async def main(do_reset: bool) -> None:
    async with SessionFactory() as session:
        if do_reset:
            await reset(session)
        elif await session.scalar(select(func.count()).select_from(User)):
            raise SystemExit("The database is not empty; rerun with --reset to wipe it first.")
        await seed(session)
    await engine.dispose()
    print(f"Demo data ready. Users: {', '.join(USERS)}; password: {DEMO_PASSWORD}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--reset", action="store_true", help="delete ALL existing data and files first"
    )
    asyncio.run(main(parser.parse_args().reset))
