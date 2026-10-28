import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from httpx import AsyncClient
from httpx_ws import AsyncWebSocketSession, WebSocketDisconnect, aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport

from app.api import ws as ws_module
from app.core.config import settings
from app.main import app
from app.realtime.bus import event_bus
from tests.helpers import ChatUser, create_group

RECEIVE_TIMEOUT = 2
SILENCE_TIMEOUT = 0.3


@pytest.fixture(autouse=True)
async def _event_bus() -> AsyncIterator[None]:
    # ASGI transports don't run the lifespan, so start the event bus by hand.
    await event_bus.start()
    yield
    await event_bus.stop()


@asynccontextmanager
async def open_ws() -> AsyncIterator[AsyncWebSocketSession]:
    # Created inside the test task: the transport's anyio cancel scope must be
    # entered and exited by the same task, which fixtures don't guarantee.
    async with (
        AsyncClient(transport=ASGIWebSocketTransport(app), base_url="http://test") as client,
        aconnect_ws("/api/ws", client) as ws,
    ):
        yield ws


@asynccontextmanager
async def connect(user: ChatUser) -> AsyncIterator[AsyncWebSocketSession]:
    async with open_ws() as ws:
        token = user.headers["Authorization"].removeprefix("Bearer ")
        await ws.send_json({"type": "auth", "token": token})
        event = await ws.receive_json(timeout=RECEIVE_TIMEOUT)
        assert event["type"] == "auth.ok"
        assert event["user"]["id"] == user.id
        yield ws


async def receive(ws: AsyncWebSocketSession) -> dict:
    return await ws.receive_json(timeout=RECEIVE_TIMEOUT)


async def assert_silent(ws: AsyncWebSocketSession) -> None:
    with pytest.raises(TimeoutError):
        await ws.receive_json(timeout=SILENCE_TIMEOUT)


def send_event(chat_id: int, text: str, client_msg_id: str | None = None) -> dict:
    return {
        "type": "message.send",
        "chat_id": chat_id,
        "text": text,
        "client_msg_id": client_msg_id or str(uuid.uuid4()),
    }


# --- handshake


async def test_rejects_invalid_token() -> None:
    async with open_ws() as ws:
        await ws.send_json({"type": "auth", "token": "garbage"})
        with pytest.raises(WebSocketDisconnect) as exc_info:
            await receive(ws)

    assert exc_info.value.code == ws_module.CLOSE_UNAUTHORIZED


async def test_closes_when_auth_does_not_arrive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ws_module, "AUTH_TIMEOUT_SECONDS", 0.1)

    async with open_ws() as ws:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            await receive(ws)

    assert exc_info.value.code == ws_module.CLOSE_UNAUTHORIZED


# --- messages


async def test_message_is_acked_and_delivered_to_members_only(client: AsyncClient, users) -> None:
    alice, bob, carol = users["alice"], users["bob"], users["carol"]
    chat = await create_group(client, alice, bob)

    async with (
        connect(alice) as alice_ws,
        connect(bob) as bob_ws,
        connect(carol) as carol_ws,
    ):
        client_msg_id = str(uuid.uuid4())
        await alice_ws.send_json(send_event(chat["id"], " hi bob ", client_msg_id))

        events = {e["type"]: e for e in [await receive(alice_ws), await receive(alice_ws)]}
        ack = events["message.ack"]
        assert ack["client_msg_id"] == client_msg_id
        assert ack["message"]["text"] == "hi bob"
        assert ack["message"]["sender"]["username"] == "alice"
        # The sender's other tabs learn about the message via message.new.
        assert events["message.new"]["message"] == ack["message"]

        delivered = await receive(bob_ws)
        assert delivered == {"type": "message.new", "message": ack["message"]}
        await assert_silent(carol_ws)

    history = await client.get(f"/api/chats/{chat['id']}/messages", headers=bob.headers)
    assert [m["id"] for m in history.json()["items"]] == [ack["message"]["id"]]


async def test_resend_is_acked_again_but_delivered_once(client: AsyncClient, users) -> None:
    alice, bob = users["alice"], users["bob"]
    chat = await create_group(client, alice, bob)

    async with connect(alice) as alice_ws, connect(bob) as bob_ws:
        event = send_event(chat["id"], "once")
        await alice_ws.send_json(event)
        first = await receive(bob_ws)

        await alice_ws.send_json(event)
        received = [await receive(alice_ws) for _ in range(3)]
        acks = [e for e in received if e["type"] == "message.ack"]

        assert len(acks) == 2
        assert acks[0]["message"]["id"] == acks[1]["message"]["id"] == first["message"]["id"]
        await assert_silent(bob_ws)


async def test_message_sent_over_rest_is_pushed(client: AsyncClient, users) -> None:
    alice, bob = users["alice"], users["bob"]
    chat = await create_group(client, alice, bob)

    async with connect(bob) as bob_ws:
        response = await client.post(
            f"/api/chats/{chat['id']}/messages", json={"text": "via rest"}, headers=alice.headers
        )

        assert await receive(bob_ws) == {"type": "message.new", "message": response.json()}


async def test_user_receives_events_on_every_connection(client: AsyncClient, users) -> None:
    alice, bob = users["alice"], users["bob"]
    chat = await create_group(client, alice, bob)

    async with connect(bob) as tab1, connect(bob) as tab2:
        await client.post(
            f"/api/chats/{chat['id']}/messages", json={"text": "hey"}, headers=alice.headers
        )

        assert (await receive(tab1))["message"]["text"] == "hey"
        assert (await receive(tab2))["message"]["text"] == "hey"


# --- errors


async def test_errors_keep_the_connection_open(client: AsyncClient, users) -> None:
    alice, carol = users["alice"], users["carol"]
    foreign_chat = await create_group(client, carol)

    async with connect(alice) as ws:
        await ws.send_text("not json")
        error = await receive(ws)
        assert (error["type"], error["code"]) == ("error", "invalid_event")

        await ws.send_json({"type": "message.send", "chat_id": 1, "client_msg_id": "abc"})
        error = await receive(ws)
        assert error["code"] == "invalid_event"
        assert error["client_msg_id"] == "abc"
        assert "client_msg_id" in error["detail"]

        empty = send_event(foreign_chat["id"], "")
        await ws.send_json(empty)
        error = await receive(ws)
        assert error["code"] == "invalid_event"
        assert error["client_msg_id"] == empty["client_msg_id"]
        assert "text or attachments" in error["detail"]

        event = send_event(foreign_chat["id"], "let me in")
        await ws.send_json(event)
        error = await receive(ws)
        assert error["code"] == "not_found"
        assert error["client_msg_id"] == event["client_msg_id"]

        await ws.send_json({"type": "ping"})
        assert await receive(ws) == {"type": "pong"}


# --- chat changes


async def test_chat_changes_are_announced(client: AsyncClient, users) -> None:
    alice, bob, carol = users["alice"], users["bob"], users["carol"]

    async with connect(bob) as bob_ws, connect(carol) as carol_ws:
        chat = await create_group(client, alice, bob)
        assert await receive(bob_ws) == {"type": "chat.updated", "chat_id": chat["id"]}

        await client.post(
            f"/api/chats/{chat['id']}/members", json={"user_id": carol.id}, headers=alice.headers
        )
        assert await receive(carol_ws) == {"type": "chat.updated", "chat_id": chat["id"]}
        assert await receive(bob_ws) == {"type": "chat.updated", "chat_id": chat["id"]}

        await client.delete(f"/api/chats/{chat['id']}/members/{bob.id}", headers=alice.headers)
        # The removed user is told too, so their client can drop the chat.
        assert await receive(bob_ws) == {"type": "chat.updated", "chat_id": chat["id"]}
        assert await receive(carol_ws) == {"type": "chat.updated", "chat_id": chat["id"]}


# --- stage 6 events


async def test_edits_reactions_and_reads_are_pushed(client: AsyncClient, users) -> None:
    alice, bob = users["alice"], users["bob"]
    chat = await create_group(client, alice, bob)
    message = (
        await client.post(
            f"/api/chats/{chat['id']}/messages", json={"text": "hi"}, headers=alice.headers
        )
    ).json()
    url = f"/api/chats/{chat['id']}/messages/{message['id']}"

    async with connect(alice) as alice_ws, connect(bob) as bob_ws:
        await client.patch(url, json={"text": "hi there"}, headers=alice.headers)
        updated = await receive(bob_ws)
        assert updated["type"] == "message.updated"
        assert updated["message"]["text"] == "hi there"
        assert (await receive(alice_ws))["type"] == "message.updated"

        await client.put(f"{url}/reactions/🔥", headers=bob.headers)
        reacted = await receive(alice_ws)
        assert reacted["message"]["reactions"] == [
            {"emoji": "🔥", "count": 1, "user_ids": [bob.id]}
        ]
        await receive(bob_ws)

        await client.post(
            f"/api/chats/{chat['id']}/read", json={"message_id": message["id"]}, headers=bob.headers
        )
        assert await receive(alice_ws) == {
            "type": "read.updated",
            "chat_id": chat["id"],
            "user_id": bob.id,
            "last_read_message_id": message["id"],
        }


async def test_ws_send_with_reply_and_attachment(client: AsyncClient, users) -> None:
    alice, bob = users["alice"], users["bob"]
    chat = await create_group(client, alice, bob)
    original = (
        await client.post(
            f"/api/chats/{chat['id']}/messages", json={"text": "photo?"}, headers=bob.headers
        )
    ).json()
    attachment = (
        await client.post(
            f"/api/chats/{chat['id']}/attachments",
            files={"file": ("notes.txt", b"hello", "text/plain")},
            headers=alice.headers,
        )
    ).json()

    async with connect(alice) as ws:
        event = send_event(chat["id"], "")
        event |= {"reply_to_id": original["id"], "attachment_ids": [attachment["id"]]}
        await ws.send_json(event)
        ack = next(e for e in [await receive(ws), await receive(ws)] if e["type"] == "message.ack")

    assert ack["message"]["reply_to"]["id"] == original["id"]
    assert ack["message"]["attachments"][0]["filename"] == "notes.txt"


async def test_ws_send_is_rate_limited(
    client: AsyncClient, users, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "send_rate_limit", 1)
    alice = users["alice"]
    chat = await create_group(client, alice)

    async with connect(alice) as ws:
        await ws.send_json(send_event(chat["id"], "first"))
        await receive(ws)
        await receive(ws)
        second = send_event(chat["id"], "second")
        await ws.send_json(second)
        error = await receive(ws)

    assert error["code"] == "rate_limited"
    assert error["client_msg_id"] == second["client_msg_id"]
