"""Redis carries only internal UUIDs. PostgreSQL owns retries, not broker history."""

from uuid import UUID, uuid4

from dramatiq import Message
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import Retries
from redis import Redis

from oria_engine.config import Settings
from oria_engine.observability import measurement


class Publisher:
    def __init__(self, settings: Settings) -> None:
        self.client = Redis.from_url(
            settings.redis_url.get_secret_value(), socket_connect_timeout=3, socket_timeout=3
        )
        self.broker = RedisBroker(  # type: ignore[no-untyped-call]
            client=self.client,
            namespace="oria",
            middleware=[Retries(max_retries=0)],
        )

    def send(self, event_id: str) -> None:
        with measurement("queue_publish"):
            self._send(event_id)

    def _send(self, event_id: str) -> None:
        event_id = str(UUID(event_id))
        key = f"oria:event:{event_id}:publication"
        token = str(uuid4())
        if not self.client.set(key, token, nx=True, ex=150):
            return
        try:
            self.broker.enqueue(
                Message(
                    queue_name="inbound",
                    actor_name="process_inbound",
                    args=(event_id,),
                    kwargs={},
                    options={},
                )
            )
        except BaseException:
            # A failed publication must not hide the canonical event until TTL expiry.
            self.client.eval(
                "if redis.call('GET', KEYS[1]) == ARGV[1] then "
                "return redis.call('DEL', KEYS[1]) end return 0",
                1,
                key,
                token,
            )
            raise

    def close(self) -> None:
        self.broker.close()
        self.client.close()
        self.client.connection_pool.disconnect()
