"""Deterministic consent decisions gating optional encrypted onboarding; no model calls."""

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from oria_engine.db.repositories import ConsentRepository, SocialIdentityRepository
from oria_engine.db.session import Database
from oria_engine.domain.channel import HELP_TEXT, ChannelButton, ChannelMessage
from oria_engine.observability import count

if TYPE_CHECKING:
    from oria_engine.domain.onboarding import OnboardingFlow

# Collection disclosure uses the configured policy version (default 2026-10-03.2).
# Change the configured version whenever the disclosure/data use changes.
DISCLAIMER = (
    "Hi — I'm Oria, an AI astrology personality. Astrology is interpretive, not a factual "
    "or scientifically established forecast. My responses are not medical, legal, financial "
    "or other high-stakes professional advice.\n\n"
    "For personalized chart calculations, I need your birth date, birth time "
    "(exact, approximate, or unknown), and birthplace (city and country). "
    "OriaEngine will store those details for future conversations after you agree. "
    "I won't ask for unrelated identifying information: legal name, email, phone number, "
    "home address, employer, passwords, government IDs or payment details.\n\n"
    "Use /profile to inspect confirmed birth details, unfinished edits, chart status and "
    "consent, even after declining. /edit_profile corrects birth details after consent; "
    "selecting a birthplace determines coordinates and timezone. /privacy reviews this "
    "policy and lets you withdraw consent with Decline. /help lists commands. "
    "Use /delete_me (or /delete-me) and its confirmation button to delete your account. "
    "Processing stops on confirmation; cleanup retries until services acknowledge deletion. "
    "Derived chart facts are stored privately "
    "in the application database. "
    "We store internal identity, Telegram routing IDs, consent decisions and encrypted "
    "onboarding progress, including incomplete birth details. Confirmed profiles are encrypted. "
    "Send only the birth field requested. After consent, queued messages and pending replies "
    "are temporarily encrypted in PostgreSQL and erased on completion or permanent failure. "
    "Unfinished payloads expire after 24 hours and are erased when the worker next runs. "
    "Before consent, free text is discarded. Queue metadata and processing status are retained. "
    "Active chat uses SecondContext and its AI provider: filtered messages, replies and "
    "retrieved context are retained there for conversation continuity. Filtering is limited; "
    "do not include identifying or birth details in chat. Calculated chart facts are sent "
    "for interpretation and may be quoted in retained replies. Raw saved birth profiles "
    "and onboarding messages are not sent to SecondContext. A blocked AI draft may still "
    "be retained there. Declining stops further conversation processing but does not erase "
    "prior transcripts. Confirmed deletion removes profiles, consent history, application "
    "sessions, SecondContext conversations/memories and Telegram identity mapping. "
    "Minimal subject/timestamp deletion markers and unlinked update receipts remain. "
    "An encrypted reply address is retained for up to 24 hours after cleanup to retry "
    "the final confirmation; workers erase it after delivery or expiry. "
    "Backups and AI-provider retention are separate. "
    "Telegram retains messages under its own policies. You can use Decline below to stop "
    "onboarding, including after accepting; this does not delete identity, consent history "
    "or previously collected birth details.\n\n"
    "This MVP is for adults aged 18 or older. By choosing 'I'm 18+ and agree', you confirm "
    "that you are at least 18 and consent to the described birth-data use."
)
ACCEPTED_TEXT = (
    "Your consent is recorded. The next step is your birth date, but profile setup "
    "is not available in this demo yet. Please don't send birth details. "
    "Use /privacy to review the policy or decline further onboarding."
)
DECLINED_TEXT = (
    "Onboarding is stopped. Your identity, consent history and any previously collected "
    "birth details remain stored; declining does not delete data. "
    "Use /start if you change your mind."
)


class OnboardingState(StrEnum):
    CONSENT_REQUIRED = "ConsentRequired"
    CLOSED = "Closed"
    BIRTH_DATE_REQUIRED = "BirthDateRequired"
    BIRTH_TIME_REQUIRED = "BirthTimeRequired"
    BIRTH_PLACE_REQUIRED = "BirthPlaceRequired"
    BIRTH_PLACE_CONFIRMATION = "BirthPlaceConfirmation"
    BIRTH_TIME_CLARIFICATION = "BirthTimeClarification"
    PROFILE_CONFIRMATION = "ProfileConfirmation"
    COMPUTING_PROFILE = "ComputingProfile"
    ACTIVE = "Active"


@dataclass(frozen=True)
class ConsentReply:
    state: OnboardingState
    text: str = field(repr=False)
    buttons: tuple[ChannelButton, ...] = field(default=(), repr=False)


class ConsentFlow:
    def __init__(
        self, database: Database, policy_version: str, onboarding: "OnboardingFlow | None" = None
    ) -> None:
        self.database = database
        self.policy_version = policy_version
        self.onboarding = onboarding
        # Bounded even for 64-character configured versions; includes displayed copy.
        fingerprint = sha256((policy_version + "\n" + DISCLAIMER).encode()).hexdigest()[:32]
        self.buttons = (
            ChannelButton("I'm 18+ and agree", f"consent:accept:{fingerprint}"),
            ChannelButton("Decline", f"consent:decline:{fingerprint}"),
        )

    def disclosure(self, state: OnboardingState = OnboardingState.CONSENT_REQUIRED) -> ConsentReply:
        count("consent_disclosure")
        return ConsentReply(state, f"Policy {self.policy_version}\n\n{DISCLAIMER}", self.buttons)

    async def handle(self, message: ChannelMessage, *, command: str | None = None) -> ConsentReply:
        async with self.database.transaction() as session:
            user = await SocialIdentityRepository(session).get_or_create_user_for_social_identity(
                provider=message.provider,
                provider_user_id=message.provider_user_id,
                provider_chat_id=message.provider_chat_id,
            )
            return await self.handle_in_session(session, user.id, message, command=command)

    async def handle_in_session(
        self,
        session: AsyncSession,
        user_id: UUID,
        message: ChannelMessage,
        *,
        command: str | None = None,
    ) -> ConsentReply:
        """Caller owns the transaction, including its inbound idempotency anchor."""
        from oria_engine.privacy.deletion import deletion_command

        deletion_reply = await deletion_command(session, user_id, message, command)
        if deletion_reply is not None:
            return deletion_reply
        consents = ConsentRepository(session)
        stale_button = False
        if message.callback_data is not None:
            if message.callback_data == self.buttons[0].data:
                await consents.accept(user_id, self.policy_version, message.provider)
            elif message.callback_data == self.buttons[1].data:
                await consents.decline(user_id, self.policy_version, message.provider)
            elif not (self.onboarding is not None and message.callback_data.startswith("onboard:")):
                # Old policy/unknown button: never convert it into a current decision.
                stale_button = True
        latest = await consents.latest(user_id)
        if await consents.current(user_id, self.policy_version):
            state = OnboardingState.BIRTH_DATE_REQUIRED
        elif (
            latest
            and latest.policy_version == self.policy_version
            and latest.status in {"declined", "revoked"}
        ):
            state = OnboardingState.CLOSED
        else:
            state = OnboardingState.CONSENT_REQUIRED

        if command == "help":
            return ConsentReply(state, HELP_TEXT)
        if command == "profile" and self.onboarding is not None:
            return await self.onboarding.inspect_profile(session, user_id)

        if (
            stale_button
            or command == "privacy"
            or (command == "start" and state == OnboardingState.CLOSED)
        ):
            return self.disclosure(state)
        if state == OnboardingState.CONSENT_REQUIRED:
            return self.disclosure()
        if state == OnboardingState.CLOSED:
            return ConsentReply(state, DECLINED_TEXT)
        if self.onboarding is not None and command != "help":
            return await self.onboarding.handle(session, user_id, message, command=command)
        return ConsentReply(state, HELP_TEXT if command == "help" else ACCEPTED_TEXT)
