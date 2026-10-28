import logging
import time

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.services.errors import RateLimitedError

logger = logging.getLogger(__name__)


async def check_send_rate(redis: Redis, user_id: int) -> None:
    """Fixed-window limit on sent messages, shared by all backend processes via Redis.

    Fails open: if Redis is unavailable, messages are still accepted.
    """
    window = settings.send_rate_window_seconds
    key = f"ratelimit:send:{user_id}:{int(time.time() // window)}"
    try:
        async with redis.pipeline(transaction=True) as pipe:
            count, _ = await pipe.incr(key).expire(key, window).execute()
    except (RedisError, OSError):
        logger.exception("Rate limiter unavailable")
        return
    if count > settings.send_rate_limit:
        raise RateLimitedError(
            f"Too many messages: at most {settings.send_rate_limit} per {window} seconds"
        )
