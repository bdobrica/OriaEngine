"""Deterministic consent decisions and versioned storage disclosure."""

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

# Collection disclosure uses the configured policy version (default 2026-11-08.3).
# Change the configured version whenever the disclosure/data use changes.
DISCLAIMER = (
    "Hi — I'm Oria, an AI astrology personality for adults. Astrology is "
    "interpretive, not a scientifically established forecast. My responses "
    "are not medical, legal, financial or other professional advice.\n"
    "\n"
    "After you agree, OriaEngine encrypts your birth date, "
    "exact/approximate/unknown time and birthplace for chart calculations. "
    "You are responsible for what you voluntarily share about yourself, "
    "people, pets, organizations and possessions. Oria is responsible for "
    "secure storage, account isolation and the controls below.\n"
    "\n"
    "With an active profile, clearly disclosed meaningful events and "
    "entities can be learned from bounded English conversation without a "
    "separate save command. Labels, aliases, relationships, event "
    "participants, supplied dates/times/places and source/date-resolution "
    "provenance are encrypted locally. Unknown dates and times stay "
    "unknown. Saved events can resolve later date references locally. Your "
    "own birth remains in its confirmed profile, with revision references "
    "rather than duplicate birth fields. Examples, hypotheticals and "
    "recognized “don't remember this” requests do not create saved events. "
    "Extraction is limited: inspect or correct anything misunderstood. A "
    "save or change is acknowledged only with the application operation.\n"
    "\n"
    "Use /profile for confirmed birth details, unfinished edits, chart "
    "status and consent. /edit_profile corrects your own birth details "
    "after consent; selecting a birthplace sets coordinates/timezone. "
    "/memories lists saved events/entities; ask what I remember, correct "
    "an event or say “forget …”. Inspection and removal remain available "
    "without current consent. Entity removal can also remove linked "
    "events; I ask if the cascade is unclear. Forgotten UUIDs and "
    "payload-free operation receipts prevent replay. Selective removal "
    "covers local saved records and pending clarification, not earlier "
    "conversation/provider copies. SecondContext event projections and "
    "remote selective erasure are not available yet. “Don't remember” "
    "prevents additional profile-memory writes; it does not create a "
    "private chat mode.\n"
    "\n"
    "/privacy shows this policy and Decline withdraws consent. Declining "
    "stops learning, readings and setup, and clears pending questions; "
    "previously saved data remains. /delete_me (or /delete-me) opens "
    "confirmed account deletion. Processing stops on confirmation; cleanup "
    "retries until Oria and SecondContext acknowledge it. Profiles, "
    "events/entities, consent, sessions, conversations/memories and the "
    "Telegram identity mapping are erased from active stores. Minimal "
    "deletion markers and unlinked update receipts remain. An encrypted "
    "reply address lasts up to 24 hours after cleanup for the final "
    "notice. /help lists commands.\n"
    "\n"
    "We store internal identity, Telegram routing IDs, consent decisions, "
    "encrypted unfinished setup and private derived chart facts. Queued "
    "messages and replies are encrypted temporarily and erased on "
    "completion/final failure; unfinished payloads expire after 24 hours, "
    "erased when workers next run. Before consent, ordinary free text is "
    "discarded; explicit inspection/erasure requests and bounded pending "
    "answers use this temporary queue. Queue metadata remains. Encrypted "
    "date/record-selection questions and conversation focus expire 24 "
    "hours from their reference message and clear on withdrawal.\n"
    "\n"
    "Active readings use SecondContext and its AI provider. Filtered chat, "
    "replies and retrieved context are retained there; volunteered context "
    "may appear. Obvious secrets and recognized birth "
    "clauses/continuations are held locally; filtering is limited. Raw "
    "saved birth profiles and onboarding messages are not sent there. "
    "Calculated facts can be quoted in retained replies; even a blocked "
    "draft may be retained. Local memory controls do not call that "
    "provider. Backups, AI-provider retention and Telegram history have "
    "separate lifecycles.\n"
    "\n"
    "By choosing “I'm 18+ and agree”, you confirm you are at least 18 and "
    "consent to this data use.\n"
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
        if self.onboarding is not None:
            from oria_engine.domain.knowledge import KnowledgeConversation

            memory_reply = await KnowledgeConversation(
                session, self.onboarding.encryption, self.policy_version
            ).controls(user_id, message, command)
            if memory_reply is not None:
                return ConsentReply(state, memory_reply)
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
