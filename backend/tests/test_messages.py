import uuid

import pytest
from httpx import AsyncClient

from tests.helpers import ChatUser, create_group


async def send(client: AsyncClient, user: ChatUser, chat_id: int, text: str, **extra) -> dict:
    response = await client.post(
        f"/api/chats/{chat_id}/messages", json={"text": text, **extra}, headers=user.headers
    )
    assert response.status_code == 201, response.text
    return response.json()


async def history(client: AsyncClient, user: ChatUser, chat_id: int, **params) -> dict:
    response = await client.get(
        f"/api/chats/{chat_id}/messages", params=params, headers=user.headers
    )
    assert response.status_code == 200, response.text
    return response.json()


async def search(client: AsyncClient, user: ChatUser, chat_id: int, q: str, **params) -> dict:
    response = await client.get(
        f"/api/chats/{chat_id}/messages/search", params={"q": q, **params}, headers=user.headers
    )
    assert response.status_code == 200, response.text
    return response.json()


def texts(page: dict) -> list[str]:
    return [m["text"] for m in page["items"]]


@pytest.fixture
async def chat(client: AsyncClient, users) -> dict:
    return await create_group(client, users["alice"], users["bob"])


# --- sending


async def test_send_message(client: AsyncClient, users, chat) -> None:
    message = await send(client, users["bob"], chat["id"], "  Hello!  ")

    assert message["chat_id"] == chat["id"]
    assert message["text"] == "Hello!"
    assert message["sender"]["username"] == "bob"
    assert message["client_msg_id"] is None


async def test_send_requires_membership(client: AsyncClient, users, chat) -> None:
    response = await client.post(
        f"/api/chats/{chat['id']}/messages", json={"text": "hi"}, headers=users["carol"].headers
    )

    assert response.status_code == 404


@pytest.mark.parametrize("text", ["", "   ", "x" * 4001])
async def test_send_validates_text(client: AsyncClient, users, chat, text: str) -> None:
    response = await client.post(
        f"/api/chats/{chat['id']}/messages", json={"text": text}, headers=users["alice"].headers
    )

    assert response.status_code == 422


async def test_resend_with_same_client_msg_id_is_idempotent(
    client: AsyncClient, users, chat
) -> None:
    alice = users["alice"]
    client_msg_id = str(uuid.uuid4())
    first = await send(client, alice, chat["id"], "once", client_msg_id=client_msg_id)

    retry = await client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"text": "once", "client_msg_id": client_msg_id},
        headers=alice.headers,
    )

    assert retry.status_code == 200
    assert retry.json() == first
    assert texts(await history(client, alice, chat["id"])) == ["once"]


async def test_same_client_msg_id_from_other_sender_is_separate(
    client: AsyncClient, users, chat
) -> None:
    client_msg_id = str(uuid.uuid4())

    a = await send(client, users["alice"], chat["id"], "a", client_msg_id=client_msg_id)
    b = await send(client, users["bob"], chat["id"], "b", client_msg_id=client_msg_id)

    assert a["id"] != b["id"]


# --- history


async def test_history_pages_upwards(client: AsyncClient, users, chat) -> None:
    alice = users["alice"]
    for i in range(1, 6):
        await send(client, alice, chat["id"], f"m{i}")

    page = await history(client, alice, chat["id"], limit=2)
    assert texts(page) == ["m4", "m5"]
    assert page["has_more"] is True

    page = await history(client, alice, chat["id"], limit=2, before_id=page["items"][0]["id"])
    assert texts(page) == ["m2", "m3"]
    assert page["has_more"] is True

    page = await history(client, alice, chat["id"], limit=2, before_id=page["items"][0]["id"])
    assert texts(page) == ["m1"]
    assert page["has_more"] is False


async def test_history_of_empty_chat(client: AsyncClient, users, chat) -> None:
    page = await history(client, users["alice"], chat["id"])

    assert page == {"items": [], "has_more": False}


async def test_history_is_per_chat_and_members_only(client: AsyncClient, users, chat) -> None:
    alice, carol = users["alice"], users["carol"]
    other = await create_group(client, alice, carol)
    await send(client, alice, chat["id"], "in chat")
    await send(client, alice, other["id"], "in other")

    assert texts(await history(client, alice, chat["id"])) == ["in chat"]
    response = await client.get(f"/api/chats/{chat['id']}/messages", headers=carol.headers)
    assert response.status_code == 404


async def test_removed_member_loses_access(client: AsyncClient, users, chat) -> None:
    alice, bob = users["alice"], users["bob"]
    await send(client, bob, chat["id"], "bye")
    await client.delete(f"/api/chats/{chat['id']}/members/{bob.id}", headers=alice.headers)

    read = await client.get(f"/api/chats/{chat['id']}/messages", headers=bob.headers)
    write = await client.post(
        f"/api/chats/{chat['id']}/messages", json={"text": "hi"}, headers=bob.headers
    )

    assert (read.status_code, write.status_code) == (404, 404)
    # The message itself stays in the history.
    assert texts(await history(client, alice, chat["id"])) == ["bye"]


# --- search


async def test_search_is_case_insensitive_substring_newest_first(
    client: AsyncClient, users, chat
) -> None:
    alice, bob = users["alice"], users["bob"]
    await send(client, alice, chat["id"], "Meeting at noon")
    await send(client, bob, chat["id"], "lunch?")
    await send(client, bob, chat["id"], "the MEETING moved")

    assert texts(await search(client, alice, chat["id"], "meeting")) == [
        "the MEETING moved",
        "Meeting at noon",
    ]
    assert texts(await search(client, alice, chat["id"], "nothing")) == []


async def test_search_paginates(client: AsyncClient, users, chat) -> None:
    alice = users["alice"]
    for i in range(1, 4):
        await send(client, alice, chat["id"], f"note {i}")

    page = await search(client, alice, chat["id"], "note", limit=2)
    assert texts(page) == ["note 3", "note 2"]
    assert page["has_more"] is True

    page = await search(
        client, alice, chat["id"], "note", limit=2, before_id=page["items"][-1]["id"]
    )
    assert texts(page) == ["note 1"]
    assert page["has_more"] is False


async def test_search_is_scoped_to_chat_and_escapes_wildcards(
    client: AsyncClient, users, chat
) -> None:
    alice, carol = users["alice"], users["carol"]
    other = await create_group(client, alice, carol)
    await send(client, alice, chat["id"], "100% sure")
    await send(client, alice, chat["id"], "1000 times")
    await send(client, alice, other["id"], "100% elsewhere")

    assert texts(await search(client, alice, chat["id"], "100%")) == ["100% sure"]
    response = await client.get(
        f"/api/chats/{chat['id']}/messages/search", params={"q": "x"}, headers=carol.headers
    )
    assert response.status_code == 404


# --- chat list


async def test_chat_list_shows_last_message_and_orders_by_activity(
    client: AsyncClient, users
) -> None:
    alice, bob, carol = users["alice"], users["bob"], users["carol"]
    first = await create_group(client, alice, bob, title="First")
    second = await create_group(client, alice, carol, title="Second")
    await send(client, bob, first["id"], "old")
    await send(client, bob, first["id"], "newest in first")

    chats = (await client.get("/api/chats", headers=alice.headers)).json()

    assert [c["title"] for c in chats] == ["First", "Second"]
    assert chats[0]["last_message"]["text"] == "newest in first"
    assert chats[0]["last_message"]["sender"]["username"] == "bob"
    assert chats[1]["last_message"] is None

    await send(client, carol, second["id"], "now second is active")
    chats = (await client.get("/api/chats", headers=alice.headers)).json()
    assert [c["title"] for c in chats] == ["Second", "First"]
