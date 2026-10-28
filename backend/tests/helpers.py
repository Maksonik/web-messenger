from dataclasses import dataclass

from httpx import AsyncClient

DEFAULT_PASSWORD = "correct-horse-battery"


@dataclass
class ChatUser:
    id: int
    username: str
    headers: dict[str, str]


async def register(
    client: AsyncClient,
    username: str,
    password: str = DEFAULT_PASSWORD,
    display_name: str | None = None,
) -> dict:
    payload = {"username": username, "password": password}
    if display_name is not None:
        payload["display_name"] = display_name
    response = await client.post("/api/auth/register", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def bearer(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


async def create_group(
    client: AsyncClient, owner: ChatUser, *members: ChatUser, title: str = "Team"
) -> dict:
    response = await client.post(
        "/api/chats/group",
        json={"title": title, "member_ids": [m.id for m in members]},
        headers=owner.headers,
    )
    assert response.status_code == 201, response.text
    return response.json()
