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
    callback_data: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class ChannelButton:
    text: str
    data: str


class ChannelClient(Protocol):
    async def send_text(
        self, provider_chat_id: str, text: str, *, buttons: tuple[ChannelButton, ...] = ()
    ) -> None:
        """Send plain text to a trusted channel routing identifier."""


HELP_TEXT = (
    "Available commands: /start, /help and /privacy. Use /start to review consent. "
    "Birth-profile setup is coming next. "
    "Please don't send birth details or other personal information yet."
)
