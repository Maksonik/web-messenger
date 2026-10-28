from dataclasses import dataclass

import pytest
from httpx import AsyncClient

from tests.helpers import bearer, register


@dataclass
class ChatUser:
    id: int
    username: str
    headers: dict[str, str]


@pytest.fixture
async def users(client: AsyncClient) -> dict[str, ChatUser]:
    result = {}
    for name in ("alice", "bob", "carol", "dave"):
        body = await register(client, name)
        result[name] = ChatUser(body["user"]["id"], name, bearer(body["access_token"]))
    return result


async def create_group(client: AsyncClient, owner: ChatUser, *members: ChatUser) -> dict:
    response = await client.post(
        "/api/chats/group",
        json={"title": "Team", "member_ids": [m.id for m in members]},
        headers=owner.headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def member_roles(chat: dict) -> dict[str, str]:
    return {m["user"]["username"]: m["role"] for m in chat["members"]}


async def chat_ids(client: AsyncClient, user: ChatUser) -> list[int]:
    response = await client.get("/api/chats", headers=user.headers)
    assert response.status_code == 200
    return [chat["id"] for chat in response.json()]


# --- direct chats


async def test_direct_chat_is_created_once_per_pair(client: AsyncClient, users) -> None:
    alice, bob = users["alice"], users["bob"]

    created = await client.post(
        "/api/chats/direct", json={"user_id": bob.id}, headers=alice.headers
    )
    assert created.status_code == 201
    chat = created.json()
    assert chat["type"] == "direct"
    assert chat["title"] is None
    assert member_roles(chat) == {"alice": "member", "bob": "member"}

    again = await client.post("/api/chats/direct", json={"user_id": alice.id}, headers=bob.headers)
    assert again.status_code == 200
    assert again.json()["id"] == chat["id"]


async def test_direct_chat_with_self_or_unknown_user(client: AsyncClient, users) -> None:
    alice = users["alice"]

    to_self = await client.post(
        "/api/chats/direct", json={"user_id": alice.id}, headers=alice.headers
    )
    unknown = await client.post("/api/chats/direct", json={"user_id": 999}, headers=alice.headers)

    assert to_self.status_code == 400
    assert unknown.status_code == 404


async def test_direct_chat_has_no_member_management(client: AsyncClient, users) -> None:
    alice, bob, carol = users["alice"], users["bob"], users["carol"]
    chat = (
        await client.post("/api/chats/direct", json={"user_id": bob.id}, headers=alice.headers)
    ).json()

    add = await client.post(
        f"/api/chats/{chat['id']}/members", json={"user_id": carol.id}, headers=alice.headers
    )
    rename = await client.patch(
        f"/api/chats/{chat['id']}", json={"title": "x"}, headers=alice.headers
    )
    leave = await client.delete(
        f"/api/chats/{chat['id']}/members/{alice.id}", headers=alice.headers
    )

    assert (add.status_code, rename.status_code, leave.status_code) == (400, 400, 400)


# --- group chats and listing


async def test_create_group_chat(client: AsyncClient, users) -> None:
    alice, bob, carol = users["alice"], users["bob"], users["carol"]

    response = await client.post(
        "/api/chats/group",
        json={"title": "  Team  ", "member_ids": [bob.id, carol.id, bob.id, alice.id]},
        headers=alice.headers,
    )

    assert response.status_code == 201
    chat = response.json()
    assert chat["type"] == "group"
    assert chat["title"] == "Team"
    assert member_roles(chat) == {"alice": "admin", "bob": "member", "carol": "member"}


async def test_create_group_validation(client: AsyncClient, users) -> None:
    alice = users["alice"]

    unknown = await client.post(
        "/api/chats/group", json={"title": "Team", "member_ids": [999]}, headers=alice.headers
    )
    blank_title = await client.post(
        "/api/chats/group", json={"title": "   "}, headers=alice.headers
    )

    assert unknown.status_code == 404
    assert blank_title.status_code == 422


async def test_list_and_get_only_own_chats(client: AsyncClient, users) -> None:
    alice, bob, carol = users["alice"], users["bob"], users["carol"]
    group = await create_group(client, alice, bob)
    direct = (
        await client.post("/api/chats/direct", json={"user_id": carol.id}, headers=alice.headers)
    ).json()

    assert await chat_ids(client, alice) == [direct["id"], group["id"]]
    assert await chat_ids(client, bob) == [group["id"]]
    assert await chat_ids(client, users["dave"]) == []

    own = await client.get(f"/api/chats/{group['id']}", headers=bob.headers)
    foreign = await client.get(f"/api/chats/{group['id']}", headers=carol.headers)
    missing = await client.get("/api/chats/999", headers=alice.headers)

    assert own.status_code == 200
    assert own.json() == group
    assert foreign.status_code == 404
    assert missing.status_code == 404


async def test_chats_require_auth(client: AsyncClient) -> None:
    assert (await client.get("/api/chats")).status_code == 401


# --- group administration


async def test_admin_renames_group(client: AsyncClient, users) -> None:
    alice, bob = users["alice"], users["bob"]
    chat = await create_group(client, alice, bob)

    by_admin = await client.patch(
        f"/api/chats/{chat['id']}", json={"title": "Renamed"}, headers=alice.headers
    )
    by_member = await client.patch(
        f"/api/chats/{chat['id']}", json={"title": "Hacked"}, headers=bob.headers
    )

    assert by_admin.status_code == 200
    assert by_admin.json()["title"] == "Renamed"
    assert by_member.status_code == 403


async def test_admin_adds_member(client: AsyncClient, users) -> None:
    alice, bob, carol = users["alice"], users["bob"], users["carol"]
    chat = await create_group(client, alice, bob)
    url = f"/api/chats/{chat['id']}/members"

    added = await client.post(url, json={"user_id": carol.id}, headers=alice.headers)

    assert added.status_code == 201
    assert added.json()["user"]["username"] == "carol"
    assert added.json()["role"] == "member"
    assert chat["id"] in await chat_ids(client, carol)

    duplicate = await client.post(url, json={"user_id": carol.id}, headers=alice.headers)
    unknown = await client.post(url, json={"user_id": 999}, headers=alice.headers)
    assert duplicate.status_code == 409
    assert unknown.status_code == 404


async def test_only_admin_adds_members(client: AsyncClient, users) -> None:
    alice, bob, carol, dave = users["alice"], users["bob"], users["carol"], users["dave"]
    chat = await create_group(client, alice, bob)
    url = f"/api/chats/{chat['id']}/members"

    by_member = await client.post(url, json={"user_id": carol.id}, headers=bob.headers)
    by_outsider = await client.post(url, json={"user_id": carol.id}, headers=dave.headers)

    assert by_member.status_code == 403
    assert by_outsider.status_code == 404


async def test_admin_removes_member(client: AsyncClient, users) -> None:
    alice, bob, carol = users["alice"], users["bob"], users["carol"]
    chat = await create_group(client, alice, bob, carol)

    removed = await client.delete(
        f"/api/chats/{chat['id']}/members/{bob.id}", headers=alice.headers
    )

    assert removed.status_code == 204
    assert await chat_ids(client, bob) == []
    after = await client.get(f"/api/chats/{chat['id']}", headers=alice.headers)
    assert member_roles(after.json()) == {"alice": "admin", "carol": "member"}

    again = await client.delete(f"/api/chats/{chat['id']}/members/{bob.id}", headers=alice.headers)
    assert again.status_code == 404


async def test_member_cannot_remove_others_but_can_leave(client: AsyncClient, users) -> None:
    alice, bob, carol = users["alice"], users["bob"], users["carol"]
    chat = await create_group(client, alice, bob, carol)

    kick = await client.delete(f"/api/chats/{chat['id']}/members/{carol.id}", headers=bob.headers)
    leave = await client.delete(f"/api/chats/{chat['id']}/members/{bob.id}", headers=bob.headers)

    assert kick.status_code == 403
    assert leave.status_code == 204
    assert await chat_ids(client, bob) == []


async def test_last_admin_cannot_leave(client: AsyncClient, users) -> None:
    alice, bob = users["alice"], users["bob"]
    chat = await create_group(client, alice, bob)

    response = await client.delete(
        f"/api/chats/{chat['id']}/members/{alice.id}", headers=alice.headers
    )

    assert response.status_code == 409
