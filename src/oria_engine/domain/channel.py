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
    "I'm Oria, an AI astrology personality for adults 18+. Astrology is interpretive, "
    "not a scientifically established forecast or professional advice.\n\n"
    "/start — review consent or resume setup.\n"
    "/profile — inspect saved details, unfinished edits, chart status and consent.\n"
    "/edit_profile — correct date, time or place, then confirm to recalculate.\n"
    "/retry_profile — retry a missing or outdated chart calculation.\n"
    "/privacy — review storage and withdraw consent with Decline.\n"
    "/delete_me (or /delete-me) — request account deletion, then explicitly confirm.\n"
    "/help — show these commands.\n\n"
    "Editing and readings require current consent. Send birth details only when setup "
    "requests them. With an active profile, ask about your natal chart, transits today, "
    "or transits on YYYY-MM-DD. Keep identifying and birth details out of chat. "
    "Declining stops readings and setup but does not erase data. Confirmed deletion stops "
    "processing and retries cleanup across Oria and SecondContext."
)
