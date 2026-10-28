"""Fan-out of realtime events to WebSocket connections.

Every backend process subscribes to one Redis channel. Publishing sends
{"to": [user ids], "event": {...}} there, and each process delivers the event to
the sockets of those users that are connected to it. This lets several workers
or containers serve WebSockets side by side.
"""

import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from fastapi import WebSocket
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.redis import redis_client

logger = logging.getLogger(__name__)

CHANNEL = "messenger:events"


class Connection:
    """One WebSocket; outgoing events go through a queue so slow clients don't block others."""

    MAX_QUEUE = 1000

    def __init__(self, websocket: WebSocket, user_id: int) -> None:
        self.websocket = websocket
        self.user_id = user_id
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(self.MAX_QUEUE)

    def send(self, event: dict[str, Any]) -> None:
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("Dropping event for slow client (user %s)", self.user_id)

    async def run_writer(self) -> None:
        while True:
            event = await self._queue.get()
            await self.websocket.send_json(event)


class EventBus:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._connections: dict[int, set[Connection]] = defaultdict(set)
        self._listener: asyncio.Task[None] | None = None

    async def start(self) -> None:
        pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
        await pubsub.subscribe(CHANNEL)
        self._listener = asyncio.create_task(self._listen(pubsub))

    async def stop(self) -> None:
        if self._listener is not None:
            self._listener.cancel()
            await asyncio.gather(self._listener, return_exceptions=True)
            self._listener = None

    def register(self, connection: Connection) -> None:
        self._connections[connection.user_id].add(connection)

    def unregister(self, connection: Connection) -> None:
        connections = self._connections.get(connection.user_id)
        if connections is not None:
            connections.discard(connection)
            if not connections:
                del self._connections[connection.user_id]

    async def publish(self, user_ids: Iterable[int], event: dict[str, Any]) -> None:
        """Best effort: the data is already in the database, so a Redis outage only delays
        delivery until clients reload."""
        payload = json.dumps({"to": sorted(set(user_ids)), "event": event})
        try:
            await self._redis.publish(CHANNEL, payload)
        except (RedisError, OSError):
            logger.exception("Failed to publish %s", event.get("type"))

    async def _listen(self, pubsub) -> None:
        try:
            async for message in pubsub.listen():
                data = json.loads(message["data"])
                for user_id in data["to"]:
                    for connection in self._connections.get(user_id, ()):
                        connection.send(data["event"])
        finally:
            await pubsub.aclose()


event_bus = EventBus(redis_client)
