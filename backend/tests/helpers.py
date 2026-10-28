from httpx import AsyncClient

DEFAULT_PASSWORD = "correct-horse-battery"


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
