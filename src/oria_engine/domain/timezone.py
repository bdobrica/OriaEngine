"""Explicit current-timezone preference; never inferred or forwarded to context."""

from zoneinfo import ZoneInfoNotFoundError

from oria_engine.db.models import User
from oria_engine.domain.birth_time import birth_zone
from oria_engine.domain.channel import ChannelMessage
from oria_engine.domain.consent import ConsentReply, OnboardingState


def timezone_reply(user: User, message: ChannelMessage) -> ConsentReply:
    parts = message.text.strip().split()
    if len(parts) == 2 and parts[1] == "clear":
        user.current_timezone = None
        text = "Your current timezone preference has been removed."
    elif len(parts) == 2:
        try:
            birth_zone(parts[1])
        except (ZoneInfoNotFoundError, ValueError):
            text = (
                "That timezone isn't supported. Use an IANA name, "
                "for example Europe/Bucharest or UTC."
            )
        else:
            user.current_timezone = parts[1]
            text = (
                f"Current timezone saved: {parts[1]}. "
                "I'll use it for relative dates and local times. "
                "Please resend your question."
            )
    else:
        text = (
            f"Current timezone: {user.current_timezone or 'not set'}. "
            "To save your current timezone, send /timezone Europe/Bucharest (use your own "
            "IANA timezone). This optional preference is stored in your Oria profile, "
            "not sent to the AI service, and removed with account deletion. "
            "Use /timezone clear to remove it. It doesn't change your birth chart."
        )
    return ConsentReply(OnboardingState.ACTIVE, text)
