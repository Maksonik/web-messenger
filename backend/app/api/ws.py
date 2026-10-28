"""WebSocket endpoint: one connection per client tab, multiplexing all of the user's chats.

Protocol (JSON text frames):
  1. Client sends {"type": "auth", "token": "<access token>"} within AUTH_TIMEOUT_SECONDS.
     On success the server replies auth.ok, otherwise closes with code 4401.
  2. Client → server:
       {"type": "message.send", "chat_id", "text", "client_msg_id": "<uuid>",
        "reply_to_id"?, "attachment_ids"?}
       {"type": "ping"}
  Server → client event types are listed in app.realtime.events.
"""

import asyncio
import json
import uuid
from typing import Annotated, Any, Literal

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, TypeAdapter, ValidationError, model_validator

from app.core.db import SessionFactory
from app.core.redis import redis_client
from app.core.security import decode_access_token
from app.models import User
from app.realtime.bus import Connection, event_bus
from app.realtime.events import message_payload, notify_new_message
from app.schemas.message import AttachmentIds, OptionalMessageText
from app.schemas.user import UserRead
from app.services import messages as messages_service
from app.services.errors import ServiceError
from app.services.rate_limit import check_send_rate

router = APIRouter()

AUTH_TIMEOUT_SECONDS = 10
CLOSE_UNAUTHORIZED = 4401


class AuthEvent(BaseModel):
    type: Literal["auth"]
    token: str


class SendMessageEvent(BaseModel):
    type: Literal["message.send"]
    chat_id: int
    text: OptionalMessageText = ""
    client_msg_id: uuid.UUID
    reply_to_id: int | None = None
    attachment_ids: AttachmentIds = []

    @model_validator(mode="after")
    def _not_empty(self) -> "SendMessageEvent":
        if not self.text and not self.attachment_ids:
            raise ValueError("A message needs text or attachments")
        return self


class PingEvent(BaseModel):
    type: Literal["ping"]


ClientEvent = TypeAdapter(Annotated[SendMessageEvent | PingEvent, Field(discriminator="type")])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        user = await _authenticate(websocket)
    except WebSocketDisconnect:
        return
    if user is None:
        await websocket.close(code=CLOSE_UNAUTHORIZED, reason="Unauthorized")
        return

    connection = Connection(websocket, user.id)
    connection.send(
        {"type": "auth.ok", "user": UserRead.model_validate(user).model_dump(mode="json")}
    )
    event_bus.register(connection)
    writer = asyncio.create_task(connection.run_writer())
    try:
        while True:
            await _handle(connection, await websocket.receive_text())
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unregister(connection)
        writer.cancel()


async def _authenticate(websocket: WebSocket) -> User | None:
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), AUTH_TIMEOUT_SECONDS)
        user_id = decode_access_token(AuthEvent.model_validate_json(raw).token)
    except (TimeoutError, ValidationError, jwt.InvalidTokenError):
        return None
    async with SessionFactory() as session:
        return await session.get(User, user_id)


async def _handle(connection: Connection, raw: str) -> None:
    try:
        event = ClientEvent.validate_json(raw)
    except ValidationError as exc:
        connection.send(_error("invalid_event", _describe(exc), _client_msg_id_of(raw)))
        return

    if isinstance(event, PingEvent):
        connection.send({"type": "pong"})
    else:
        await _send_message(connection, event)


async def _send_message(connection: Connection, event: SendMessageEvent) -> None:
    async with SessionFactory() as session:
        sender = await session.get_one(User, connection.user_id)
        try:
            await check_send_rate(redis_client, sender.id)
            message, created = await messages_service.send_message(
                session,
                event.chat_id,
                sender,
                event.text,
                event.client_msg_id,
                reply_to_id=event.reply_to_id,
                attachment_ids=event.attachment_ids,
            )
        except ServiceError as exc:
            connection.send(_error(exc.code, exc.detail, str(event.client_msg_id)))
            return

        connection.send(
            {
                "type": "message.ack",
                "client_msg_id": str(event.client_msg_id),
                "message": message_payload(message),
            }
        )
        if created:
            await notify_new_message(session, message)


def _error(code: str, detail: str, client_msg_id: str | None = None) -> dict[str, Any]:
    event: dict[str, Any] = {"type": "error", "code": code, "detail": detail}
    if client_msg_id is not None:
        event["client_msg_id"] = client_msg_id
    return event


def _describe(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or 'event'}: {error['msg']}"
        for error in exc.errors()
    )


def _client_msg_id_of(raw: str) -> str | None:
    """Best effort, so the client can mark exactly which pending message failed."""
    try:
        value = json.loads(raw).get("client_msg_id")
    except (ValueError, AttributeError):
        return None
    return value if isinstance(value, str) else None
