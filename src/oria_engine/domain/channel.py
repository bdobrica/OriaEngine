"""Minimal in-process channel contract; message bodies must never be logged."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class ChannelMessage:
    provider: str
    provider_user_id: str = field(repr=False)
    provider_chat_id: str = field(repr=False)
    provider_message_id: str
    provider_update_id: str
    received_at: datetime
    text: str = field(repr=False)


class ChannelClient(Protocol):
    async def send_text(self, provider_chat_id: str, text: str) -> None:
        """Send plain text to a trusted channel routing identifier."""


START_TEXT = (
    "Hello, I'm Oria, an AI astrology personality. This demo is still being built. "
    "Birth-profile setup is not available yet; please don't send birth details or other "
    "personal information. Use /help to see what's available."
)
HELP_TEXT = (
    "Available commands: /start and /help. Consent and birth-profile setup are coming next. "
    "Please don't send birth details or other personal information yet."
)


async def reply_to_message(
    message: ChannelMessage, client: ChannelClient, *, command: str | None = None
) -> None:
    """Stateless baseline: no profile collection, message persistence, or model calls."""
    await client.send_text(
        message.provider_chat_id, START_TEXT if command == "start" else HELP_TEXT
    )
