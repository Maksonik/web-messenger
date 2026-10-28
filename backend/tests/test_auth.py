from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.config import settings
from app.core.db import engine
from tests.helpers import DEFAULT_PASSWORD, bearer, register


async def refresh_with(client: AsyncClient, token: str):
    """Calls /refresh with an explicit token, bypassing the client's cookie jar."""
    return await client.post("/api/auth/refresh", headers={"Cookie": f"refresh_token={token}"})


async def test_register_returns_tokens_and_sets_refresh_cookie(client: AsyncClient) -> None:
    response = await client.post(
        "/api/auth/register",
        json={"username": "alice", "password": DEFAULT_PASSWORD, "display_name": " Alice "},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.access_token_ttl_minutes * 60
    assert body["user"]["username"] == "alice"
    assert body["user"]["display_name"] == "Alice"
    assert "password_hash" not in body["user"]

    cookie = response.headers["set-cookie"]
    assert cookie.startswith("refresh_token=")
    assert "HttpOnly" in cookie
    assert "Path=/api/auth" in cookie
    assert "SameSite=strict" in cookie


async def test_display_name_defaults_to_username(client: AsyncClient) -> None:
    body = await register(client, "bob")

    assert body["user"]["display_name"] == "bob"


async def test_username_is_case_insensitive_and_unique(client: AsyncClient) -> None:
    body = await register(client, "Alice")
    assert body["user"]["username"] == "alice"

    response = await client.post(
        "/api/auth/register", json={"username": "ALICE", "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"username": "ab", "password": DEFAULT_PASSWORD},
        {"username": "bad name", "password": DEFAULT_PASSWORD},
        {"username": "x" * 33, "password": DEFAULT_PASSWORD},
        {"username": "alice", "password": "short"},
        {"username": "alice", "password": DEFAULT_PASSWORD, "display_name": "   "},
    ],
)
async def test_register_validation(client: AsyncClient, payload: dict) -> None:
    response = await client.post("/api/auth/register", json=payload)

    assert response.status_code == 422


async def test_login(client: AsyncClient) -> None:
    registered = await register(client, "alice")

    response = await client.post(
        "/api/auth/login", json={"username": "ALICE", "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 200
    assert response.json()["user"]["id"] == registered["user"]["id"]
    assert "refresh_token=" in response.headers["set-cookie"]


@pytest.mark.parametrize(
    ("username", "password"), [("alice", "wrong-password"), ("nobody", DEFAULT_PASSWORD)]
)
async def test_login_rejects_bad_credentials(
    client: AsyncClient, username: str, password: str
) -> None:
    await register(client, "alice")

    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password"


async def test_me_returns_current_user(client: AsyncClient) -> None:
    registered = await register(client, "alice")

    response = await client.get("/api/users/me", headers=bearer(registered["access_token"]))

    assert response.status_code == 200
    assert response.json() == registered["user"]


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer not-a-jwt"},
        {"Authorization": "Basic YWxpY2U6cGFzcw=="},
    ],
)
async def test_me_requires_valid_token(client: AsyncClient, headers: dict) -> None:
    response = await client.get("/api/users/me", headers=headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_me_rejects_expired_token(client: AsyncClient) -> None:
    registered = await register(client, "alice")
    expired = jwt.encode(
        {
            "sub": str(registered["user"]["id"]),
            "type": "access",
            "exp": datetime.now(UTC) - timedelta(seconds=1),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    response = await client.get("/api/users/me", headers=bearer(expired))

    assert response.status_code == 401


async def test_refresh_rotates_token(client: AsyncClient) -> None:
    registered = await register(client, "alice")
    old_token = client.cookies["refresh_token"]

    response = await client.post("/api/auth/refresh")

    assert response.status_code == 200
    assert response.json()["user"]["id"] == registered["user"]["id"]
    new_token = client.cookies["refresh_token"]
    assert new_token != old_token

    me = await client.get("/api/users/me", headers=bearer(response.json()["access_token"]))
    assert me.status_code == 200

    # The old token was single-use.
    assert (await refresh_with(client, old_token)).status_code == 401
    assert (await refresh_with(client, new_token)).status_code == 200


async def test_refresh_requires_cookie(client: AsyncClient) -> None:
    response = await client.post("/api/auth/refresh")

    assert response.status_code == 401


async def test_refresh_rejects_unknown_token(client: AsyncClient) -> None:
    response = await refresh_with(client, "made-up-token")

    assert response.status_code == 401


async def test_refresh_rejects_expired_token(client: AsyncClient) -> None:
    await register(client, "alice")
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE refresh_tokens SET expires_at = now() - interval '1 second'")
        )

    response = await client.post("/api/auth/refresh")

    assert response.status_code == 401


async def test_logout_revokes_refresh_token(client: AsyncClient) -> None:
    await register(client, "alice")
    token = client.cookies["refresh_token"]

    response = await client.post("/api/auth/logout")

    assert response.status_code == 204
    assert "refresh_token" not in client.cookies
    assert (await refresh_with(client, token)).status_code == 401


async def test_logout_without_cookie_is_noop(client: AsyncClient) -> None:
    response = await client.post("/api/auth/logout")

    assert response.status_code == 204
