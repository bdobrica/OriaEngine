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
    text: str = field(repr=False)
    data: str


class ChannelClient(Protocol):
    async def send_text(
        self, provider_chat_id: str, text: str, *, buttons: tuple[ChannelButton, ...] = ()
    ) -> None:
        """Send plain text to a trusted channel routing identifier."""


HELP_TEXT = (
    "Available commands: /start, /help and /privacy. Use /start to review consent. "
    "After accepting, /start resumes birth-profile setup. Send only the requested birth field. "
    "Local place lookup is available; chart calculation is coming next. "
    "Use /privacy to review the policy or stop onboarding."
)
