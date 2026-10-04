"""Disposable admission counters; canonical backlog accounting lives in PostgreSQL."""

import asyncio

from redis import Redis

from oria_engine.config import Settings

RATE_SCRIPT = """
local count = tonumber(redis.call('GET', KEYS[1]) or '0')
if count >= tonumber(ARGV[1]) then return 0 end
count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], 60) end
return 1
"""

LIMIT_REPLY = "Please wait a little before sending another message, then try again."
SIZE_REPLY = "Please send a shorter message (at most 4096 text units)."
UNAVAILABLE_REPLY = "I'm temporarily unavailable. Please try again in a little while."


class AdmissionRejected(Exception):
    """Permanent transport acknowledgement, with optional bounded local feedback."""

    def __init__(self, reply: str | None = None) -> None:
        super().__init__("Inbound limit reached")
        self.reply = reply


class InboundLimits:
    def __init__(self, redis: Redis, settings: Settings) -> None:
        self.redis = redis
        self.rate = settings.inbound_rate_per_minute
        self.backlog = settings.queued_jobs_per_user

    @staticmethod
    def key(provider: str, sender: str) -> str:
        # Current transport accepts only trusted Telegram numeric identifiers.
        # Never place user-controlled strings, names or message contents in Redis keys.
        if provider != "telegram" or not sender.isascii() or not sender.isdecimal():
            raise ValueError("Unsupported admission identity")
        return f"oria:abuse:telegram:{sender}"

    async def admit(self, provider: str, sender: str) -> bool:
        key = self.key(provider, sender) + ":rate"
        return bool(await asyncio.to_thread(self.redis.eval, RATE_SCRIPT, 1, key, self.rate))

    async def reject(self, provider: str, sender: str, reply: str) -> None:
        # One notice per sender/minute, shared across replicas and rejection categories.
        notify = await asyncio.to_thread(
            self.redis.set, self.key(provider, sender) + ":notice", "1", nx=True, ex=60
        )
        raise AdmissionRejected(reply if notify else None)
