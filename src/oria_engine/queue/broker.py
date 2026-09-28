"""Redis carries only internal UUIDs. PostgreSQL owns retries, not broker history."""

from dramatiq import Message
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import Retries
from redis import Redis

from oria_engine.config import Settings


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
        self.broker.enqueue(
            Message(
                queue_name="inbound",
                actor_name="process_inbound",
                args=(event_id,),
                kwargs={},
                options={},
            )
        )

    def close(self) -> None:
        self.broker.close()
        self.client.close()
        self.client.connection_pool.disconnect()
