from fastapi import APIRouter, Response, status
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import SessionDep
from app.core.redis import RedisDep

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def readiness(session: SessionDep, redis: RedisDep, response: Response) -> dict[str, str]:
    checks: dict[str, str] = {}

    try:
        await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except (SQLAlchemyError, OSError):
        checks["database"] = "error"

    try:
        await redis.ping()
        checks["redis"] = "ok"
    except (RedisError, OSError):
        checks["redis"] = "error"

    if any(value != "ok" for value in checks.values()):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return checks
