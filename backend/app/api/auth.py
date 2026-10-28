from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Response, status

from app.core.config import settings
from app.core.db import SessionDep
from app.core.security import create_access_token
from app.models import User
from app.schemas.auth import AuthResponse, LoginRequest, RegisterRequest
from app.schemas.user import UserRead
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"
# The cookie is only sent to the auth endpoints, never to the rest of the API.
REFRESH_COOKIE_PATH = "/api/auth"

RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


def _auth_response(response: Response, user: User, refresh_token: str) -> AuthResponse:
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=settings.refresh_token_ttl_days * 24 * 3600,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="strict",
    )
    access_token, expires_in = create_access_token(user.id)
    return AuthResponse(
        access_token=access_token, expires_in=expires_in, user=UserRead.model_validate(user)
    )


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest, session: SessionDep, response: Response) -> AuthResponse:
    try:
        user, refresh_token = await auth_service.register_user(session, data)
    except auth_service.UsernameTakenError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username is already taken") from None
    return _auth_response(response, user, refresh_token)


@router.post("/login")
async def login(data: LoginRequest, session: SessionDep, response: Response) -> AuthResponse:
    try:
        user, refresh_token = await auth_service.login(session, data.username, data.password)
    except auth_service.InvalidCredentialsError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password") from None
    return _auth_response(response, user, refresh_token)


@router.post("/refresh")
async def refresh(
    session: SessionDep, response: Response, refresh_token: RefreshCookie = None
) -> AuthResponse:
    if refresh_token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing refresh token")
    try:
        user, new_token = await auth_service.rotate_refresh_token(session, refresh_token)
    except auth_service.InvalidRefreshTokenError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or expired refresh token"
        ) from None
    return _auth_response(response, user, new_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    session: SessionDep, response: Response, refresh_token: RefreshCookie = None
) -> None:
    if refresh_token is not None:
        await auth_service.revoke_refresh_token(session, refresh_token)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)
