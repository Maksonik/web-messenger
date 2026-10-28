from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.api import auth, health, users
from app.core.config import settings
from app.core.db import engine
from app.core.redis import redis_client


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await redis_client.aclose()
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

    api = APIRouter(prefix="/api")
    api.include_router(auth.router)
    api.include_router(users.router)

    app.include_router(health.router)
    app.include_router(api)
    return app


app = create_app()
