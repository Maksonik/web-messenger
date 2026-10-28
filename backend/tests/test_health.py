from httpx import AsyncClient
from redis.asyncio import Redis

from app.core.redis import get_redis
from app.main import app


async def test_liveness(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_when_services_are_up(client: AsyncClient) -> None:
    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"database": "ok", "redis": "ok"}


async def test_readiness_reports_unavailable_redis(client: AsyncClient) -> None:
    unreachable = Redis.from_url("redis://localhost:1", socket_connect_timeout=1)
    app.dependency_overrides[get_redis] = lambda: unreachable

    response = await client.get("/health/ready")
    await unreachable.aclose()

    assert response.status_code == 503
    assert response.json() == {"database": "ok", "redis": "error"}
