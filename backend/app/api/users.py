from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser
from app.core.db import SessionDep
from app.models import User
from app.schemas.user import UserRead
from app.services import users as users_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
async def read_me(user: CurrentUser) -> User:
    return user


@router.get("", response_model=list[UserRead])
async def search_users(
    session: SessionDep,
    user: CurrentUser,
    q: Annotated[str, Query(min_length=1, max_length=64)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[User]:
    """Finds other users by username or display name prefix (to start a chat with)."""
    return list(await users_service.search_users(session, q, exclude_user_id=user.id, limit=limit))
