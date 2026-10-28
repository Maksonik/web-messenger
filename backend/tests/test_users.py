from httpx import AsyncClient

from tests.helpers import bearer, register


async def search(client: AsyncClient, token: str, q: str) -> list[str]:
    response = await client.get("/api/users", params={"q": q}, headers=bearer(token))
    assert response.status_code == 200, response.text
    return [user["username"] for user in response.json()]


async def test_search_by_username_or_display_name_prefix(client: AsyncClient) -> None:
    me = await register(client, "searcher")
    await register(client, "alice")
    await register(client, "alina", display_name="Lina")
    await register(client, "bob", display_name="Alfred")
    token = me["access_token"]

    assert await search(client, token, "ali") == ["alice", "alina"]
    assert await search(client, token, "AL") == ["alice", "alina", "bob"]
    assert await search(client, token, "lin") == ["alina"]
    assert await search(client, token, "lice") == []


async def test_search_excludes_current_user(client: AsyncClient) -> None:
    me = await register(client, "alice")
    await register(client, "alina")

    assert await search(client, me["access_token"], "ali") == ["alina"]


async def test_search_treats_like_wildcards_literally(client: AsyncClient) -> None:
    me = await register(client, "searcher")
    await register(client, "a_b")
    await register(client, "axb")

    assert await search(client, me["access_token"], "a_") == ["a_b"]
    assert await search(client, me["access_token"], "%") == []


async def test_search_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/api/users", params={"q": "a"})

    assert response.status_code == 401
