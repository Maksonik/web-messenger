from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

from app.schemas.user import UserRead

# The pattern is checked before lowercasing, hence A-Z.
Username = Annotated[str, StringConstraints(to_lower=True, pattern=r"^[A-Za-z0-9_]{3,32}$")]
Password = Annotated[str, StringConstraints(min_length=8, max_length=128)]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class RegisterRequest(BaseModel):
    username: Username
    password: Password
    display_name: DisplayName | None = None


class LoginRequest(BaseModel):
    username: Annotated[str, StringConstraints(to_lower=True, max_length=32)]
    password: Annotated[str, StringConstraints(max_length=128)]


class AuthResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserRead
