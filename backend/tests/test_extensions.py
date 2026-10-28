"""Read status, edit/delete, reactions, replies, mentions, rate limiting, mute, attachments."""

from urllib.parse import quote

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.services import storage
from tests.helpers import ChatUser, create_group

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00"
    b"\x00\x00\x00IEND\xaeB`\x82"
)


async def send(client: AsyncClient, user: ChatUser, chat_id: int, text: str = "", **extra) -> dict:
    response = await client.post(
        f"/api/chats/{chat_id}/messages", json={"text": text, **extra}, headers=user.headers
    )
    assert response.status_code == 201, response.text
    return response.json()


async def chat_entry(client: AsyncClient, user: ChatUser, chat_id: int) -> dict:
    chats = (await client.get("/api/chats", headers=user.headers)).json()
    return next(c for c in chats if c["id"] == chat_id)


async def history(client: AsyncClient, user: ChatUser, chat_id: int) -> list[dict]:
    response = await client.get(f"/api/chats/{chat_id}/messages", headers=user.headers)
    return response.json()["items"]


async def upload(
    client: AsyncClient,
    user: ChatUser,
    chat_id: int,
    content: bytes = PNG,
    filename: str = "pic.png",
    content_type: str = "image/png",
):
    return await client.post(
        f"/api/chats/{chat_id}/attachments",
        files={"file": (filename, content, content_type)},
        headers=user.headers,
    )


@pytest.fixture
async def chat(client: AsyncClient, users) -> dict:
    return await create_group(client, users["alice"], users["bob"])


# --- read status


async def test_unread_count_and_read_marker(client: AsyncClient, users, chat) -> None:
    alice, bob = users["alice"], users["bob"]
    first = await send(client, alice, chat["id"], "one")
    second = await send(client, alice, chat["id"], "two")
    await send(client, bob, chat["id"], "bob's own message is never unread for bob")

    assert (await chat_entry(client, bob, chat["id"]))["unread_count"] == 2
    assert (await chat_entry(client, alice, chat["id"]))["unread_count"] == 1

    url = f"/api/chats/{chat['id']}/read"
    response = await client.post(url, json={"message_id": first["id"]}, headers=bob.headers)
    assert response.json() == {"last_read_message_id": first["id"]}
    assert (await chat_entry(client, bob, chat["id"]))["unread_count"] == 1

    await client.post(url, json={"message_id": second["id"]}, headers=bob.headers)
    # The marker never moves back.
    back = await client.post(url, json={"message_id": first["id"]}, headers=bob.headers)
    assert back.json() == {"last_read_message_id": second["id"]}

    entry = await chat_entry(client, alice, chat["id"])
    readers = {m["user"]["username"]: m["last_read_message_id"] for m in entry["members"]}
    assert readers["bob"] == second["id"]


async def test_read_marker_must_point_into_the_chat(client: AsyncClient, users, chat) -> None:
    alice, carol = users["alice"], users["carol"]
    other = await create_group(client, alice, carol)
    foreign = await send(client, alice, other["id"], "elsewhere")

    response = await client.post(
        f"/api/chats/{chat['id']}/read", json={"message_id": foreign["id"]}, headers=alice.headers
    )

    assert response.status_code == 404


# --- edit and delete


async def test_author_edits_message(client: AsyncClient, users, chat) -> None:
    alice, bob = users["alice"], users["bob"]
    message = await send(client, alice, chat["id"], "helo")
    assert message["edited_at"] is None

    url = f"/api/chats/{chat['id']}/messages/{message['id']}"
    edited = await client.patch(url, json={"text": "hello"}, headers=alice.headers)
    by_other = await client.patch(url, json={"text": "hacked"}, headers=bob.headers)

    assert edited.status_code == 200
    assert edited.json()["text"] == "hello"
    assert edited.json()["edited_at"] is not None
    assert by_other.status_code == 403
    assert (await history(client, bob, chat["id"]))[0]["text"] == "hello"


async def test_author_deletes_message(client: AsyncClient, users, chat) -> None:
    alice, bob = users["alice"], users["bob"]
    message = await send(client, alice, chat["id"], "secret plan")
    url = f"/api/chats/{chat['id']}/messages/{message['id']}"
    await client.put(f"{url}/reactions/👍", headers=bob.headers)

    by_other = await client.delete(url, headers=bob.headers)
    deleted = await client.delete(url, headers=alice.headers)

    assert by_other.status_code == 403
    assert deleted.status_code == 200
    body = deleted.json()
    assert (body["deleted"], body["text"], body["reactions"]) == (True, "", [])

    # Placeholder stays in history, but not in search, unread counts or edits.
    assert (await history(client, bob, chat["id"]))[0]["deleted"] is True
    search = await client.get(
        f"/api/chats/{chat['id']}/messages/search", params={"q": "secret"}, headers=bob.headers
    )
    assert search.json()["items"] == []
    assert (await chat_entry(client, bob, chat["id"]))["unread_count"] == 0
    edit = await client.patch(url, json={"text": "again"}, headers=alice.headers)
    assert edit.status_code == 400


async def test_group_admin_can_delete_any_message(client: AsyncClient, users, chat) -> None:
    alice, bob = users["alice"], users["bob"]
    message = await send(client, bob, chat["id"], "spam")

    response = await client.delete(
        f"/api/chats/{chat['id']}/messages/{message['id']}", headers=alice.headers
    )

    assert response.status_code == 200
    assert response.json()["deleted"] is True


async def test_direct_chat_peer_cannot_delete_others_messages(client: AsyncClient, users) -> None:
    alice, bob = users["alice"], users["bob"]
    direct = (
        await client.post("/api/chats/direct", json={"user_id": bob.id}, headers=alice.headers)
    ).json()
    message = await send(client, alice, direct["id"], "mine")

    response = await client.delete(
        f"/api/chats/{direct['id']}/messages/{message['id']}", headers=bob.headers
    )

    assert response.status_code == 403


# --- reactions


async def test_reactions(client: AsyncClient, users, chat) -> None:
    alice, bob = users["alice"], users["bob"]
    message = await send(client, alice, chat["id"], "nice")
    url = f"/api/chats/{chat['id']}/messages/{message['id']}/reactions"

    await client.put(f"{url}/👍", headers=alice.headers)
    await client.put(f"{url}/👍", headers=bob.headers)
    again = await client.put(f"{url}/👍", headers=bob.headers)  # idempotent
    await client.put(f"{url}/😂", headers=bob.headers)

    assert again.status_code == 200
    reactions = (await history(client, alice, chat["id"]))[0]["reactions"]
    assert reactions == [
        {"emoji": "👍", "count": 2, "user_ids": [alice.id, bob.id]},
        {"emoji": "😂", "count": 1, "user_ids": [bob.id]},
    ]

    removed = await client.delete(f"{url}/👍", headers=alice.headers)
    assert removed.json()["reactions"][0] == {"emoji": "👍", "count": 1, "user_ids": [bob.id]}

    unsupported = await client.put(f"{url}/{quote('🍕')}", headers=alice.headers)
    assert unsupported.status_code == 400


async def test_only_members_react(client: AsyncClient, users, chat) -> None:
    message = await send(client, users["alice"], chat["id"], "x")

    response = await client.put(
        f"/api/chats/{chat['id']}/messages/{message['id']}/reactions/👍",
        headers=users["carol"].headers,
    )

    assert response.status_code == 404


# --- replies and mentions


async def test_reply_includes_preview_of_original(client: AsyncClient, users, chat) -> None:
    alice, bob = users["alice"], users["bob"]
    original = await send(client, alice, chat["id"], "Lunch at 1?")

    reply = await send(client, bob, chat["id"], "Sure", reply_to_id=original["id"])

    assert reply["reply_to"] == {
        "id": original["id"],
        "sender": original["sender"],
        "text": "Lunch at 1?",
        "deleted": False,
    }


async def test_reply_must_be_in_the_same_chat(client: AsyncClient, users, chat) -> None:
    alice, carol = users["alice"], users["carol"]
    other = await create_group(client, alice, carol)
    foreign = await send(client, alice, other["id"], "elsewhere")

    response = await client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"text": "re", "reply_to_id": foreign["id"]},
        headers=alice.headers,
    )

    assert response.status_code == 404


async def test_mentions_resolve_to_chat_members(client: AsyncClient, users, chat) -> None:
    alice, bob = users["alice"], users["bob"]

    message = await send(
        client, alice, chat["id"], "@BOB look, @carol isn't here, me@alice is an email, @alice"
    )

    # carol isn't a member, the email isn't a mention and self-mentions are skipped.
    assert message["mention_user_ids"] == [bob.id]

    edited = await client.patch(
        f"/api/chats/{chat['id']}/messages/{message['id']}",
        json={"text": "never mind"},
        headers=alice.headers,
    )
    assert edited.json()["mention_user_ids"] == []


# --- rate limiting


async def test_sending_is_rate_limited(
    client: AsyncClient, users, chat, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "send_rate_limit", 3)
    alice, bob = users["alice"], users["bob"]
    for i in range(3):
        await send(client, alice, chat["id"], f"m{i}")

    blocked = await client.post(
        f"/api/chats/{chat['id']}/messages", json={"text": "one more"}, headers=alice.headers
    )

    assert blocked.status_code == 429
    # The limit is per user.
    await send(client, bob, chat["id"], "bob is fine")


# --- mute


async def test_mute_is_per_member(client: AsyncClient, users, chat) -> None:
    alice, bob = users["alice"], users["bob"]

    response = await client.put(
        f"/api/chats/{chat['id']}/mute", json={"muted": True}, headers=bob.headers
    )

    assert response.json() == {"muted": True}
    assert (await chat_entry(client, bob, chat["id"]))["muted"] is True
    assert (await chat_entry(client, alice, chat["id"]))["muted"] is False

    await client.put(f"/api/chats/{chat['id']}/mute", json={"muted": False}, headers=bob.headers)
    assert (await chat_entry(client, bob, chat["id"]))["muted"] is False


# --- attachments


async def test_image_attachment_round_trip(client: AsyncClient, users, chat) -> None:
    alice, bob = users["alice"], users["bob"]

    uploaded = await upload(client, alice, chat["id"])
    assert uploaded.status_code == 201
    attachment = uploaded.json()
    assert (attachment["filename"], attachment["size"], attachment["is_image"]) == (
        "pic.png",
        len(PNG),
        True,
    )

    message = await send(client, alice, chat["id"], attachment_ids=[attachment["id"]])
    assert message["text"] == ""
    assert [a["id"] for a in message["attachments"]] == [attachment["id"]]

    # Any member can open the signed link, without an Authorization header.
    url = (await history(client, bob, chat["id"]))[0]["attachments"][0]["url"]
    file = await client.get(url)
    assert file.status_code == 200
    assert file.content == PNG
    assert file.headers["content-type"] == "image/png"
    assert file.headers["content-disposition"].startswith("inline")
    assert file.headers["x-content-type-options"] == "nosniff"


async def test_attachment_links_must_be_signed(client: AsyncClient, users, chat) -> None:
    attachment = (await upload(client, users["alice"], chat["id"])).json()
    tampered = attachment["url"].replace("signature=", "signature=0")
    other_file = attachment["url"].replace(
        f"/attachments/{attachment['id']}/", f"/attachments/{attachment['id'] + 1}/"
    )

    assert (await client.get(tampered)).status_code == 403
    assert (await client.get(other_file)).status_code == 403


async def test_non_image_files_are_downloaded_not_rendered(
    client: AsyncClient, users, chat
) -> None:
    html = b"<script>alert(1)</script>"
    attachment = (
        await upload(client, users["alice"], chat["id"], html, "page.html", "text/html")
    ).json()

    file = await client.get(attachment["url"])

    assert attachment["is_image"] is False
    assert file.headers["content-type"] == "application/octet-stream"
    assert file.headers["content-disposition"].startswith("attachment")


async def test_upload_limits_and_access(
    client: AsyncClient, users, chat, monkeypatch: pytest.MonkeyPatch
) -> None:
    alice, carol = users["alice"], users["carol"]
    monkeypatch.setattr(settings, "max_upload_bytes", 10)

    too_large = await upload(client, alice, chat["id"])
    not_member = await upload(client, carol, chat["id"], b"tiny", "a.txt", "text/plain")
    empty = await upload(client, alice, chat["id"], b"", "a.txt", "text/plain")

    assert too_large.status_code == 413
    assert not_member.status_code == 404
    assert empty.status_code == 400


async def test_attachments_cannot_be_reused_or_borrowed(client: AsyncClient, users, chat) -> None:
    alice, bob = users["alice"], users["bob"]
    attachment = (await upload(client, alice, chat["id"])).json()

    borrowed = await client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"attachment_ids": [attachment["id"]]},
        headers=bob.headers,
    )
    await send(client, alice, chat["id"], attachment_ids=[attachment["id"]])
    reused = await client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"attachment_ids": [attachment["id"]]},
        headers=alice.headers,
    )
    empty = await client.post(
        f"/api/chats/{chat['id']}/messages", json={"text": "  "}, headers=alice.headers
    )

    assert (borrowed.status_code, reused.status_code, empty.status_code) == (400, 400, 422)


async def test_deleting_message_removes_its_files(client: AsyncClient, users, chat) -> None:
    alice = users["alice"]
    attachment = (await upload(client, alice, chat["id"])).json()
    message = await send(client, alice, chat["id"], "see pic", attachment_ids=[attachment["id"]])
    files_before = {p.name for p in storage._root().rglob("*") if p.is_file()}

    deleted = await client.delete(
        f"/api/chats/{chat['id']}/messages/{message['id']}", headers=alice.headers
    )

    assert deleted.json()["attachments"] == []
    files_after = {p.name for p in storage._root().rglob("*") if p.is_file()}
    assert len(files_before - files_after) == 1
    assert (await client.get(attachment["url"])).status_code == 404
