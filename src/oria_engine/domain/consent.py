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

# Collection disclosure uses the configured policy version (default 2026-11-10.1).
# Change the configured version whenever the disclosure/data use changes.
DISCLAIMER = (
    "Hi — I'm Oria, an AI astrology personality for adults. Astrology is interpretive, not a "
    "scientifically established forecast or professional advice.\n\n"
    "After agreement, Oria encrypts your birth date, exact/approximate/unknown time and "
    "birthplace for calculations. You are responsible for what you voluntarily share about "
    "yourself, people, pets, organizations and possessions. Oria is responsible for secure "
    "storage, account isolation and controls.\n\n"
    "With an active profile, bounded English conversation can teach events/entities. "
    "Labels, aliases, relationships, participants, dates/times/places and provenance are "
    "encrypted locally. Examples, hypotheticals and “don't remember this” skip additional "
    "canonical/interpretation learning; this is not private-chat mode.\n\n"
    "Compatibility and event readings use calculated facts and house themes. Date-only charts "
    "use a labeled noon-UTC sample, not a known time; houses need suitable inputs. Ratings are "
    "interpretations, not probabilities.\n\n"
    "Optional linked memory sends SecondContext bounded labels/relationships, event types, "
    "participant links, UUIDs/revisions, topics, significance and filtered interpretations. Raw "
    "dates/times/places, birth inputs, aliases and source messages are not projected. Ranking "
    "and house-topic tags are heuristic interpretation, not calculated placements. Recall "
    "checks current references.\n\n"
    "Optional history replays bounded earlier accepted dialogue to SecondContext's "
    "model, including eligible prepared local exchanges. Accepted replies may be "
    "retained/replayed even if Telegram delivery fails. Rejected drafts are excluded from "
    "replay but may remain in retry/provider storage. Pending payloads expire; accepted history "
    "remains until session/subject erasure. Replay does not automatically extract memories. "
    "When observation/adaptive selection is enabled, OpenAI Decisions also processes current "
    "and bounded earlier dialogue to assess context relevance, separately from generation.\n\n"
    "/profile shows birth details, chart status and consent; /edit_profile confirms own-birth "
    "changes. /memories lists saved context; ask what I remember, correct an event or say "
    "“forget …”. Inspection and removal remain available without consent. Entity removal can "
    "include linked events; I ask if unclear. Removal queues linked summaries and entire linked "
    "conversation sessions, including drafts/results. It stays pending until acknowledged. "
    "Independent chat/provider copies have separate retention. Payload-free UUID/revision "
    "fences prevent delayed recreation.\n\n"
    "/privacy shows this policy; Decline stops learning/readings/setup, cancels late "
    "writes/delivery and clears pending questions and history payloads. Saved accepted "
    "history/data remains; erasure retries. /delete_me requests confirmed account deletion, "
    "stopping processing and retrying cleanup until Oria/SecondContext acknowledge it. "
    "Profiles, records, projections, consent, sessions, conversations/memories and Telegram "
    "identity are erased from active stores. Minimal deletion markers and unlinked receipts "
    "remain. An encrypted final-reply address lasts up to 24 hours after cleanup.\n\n"
    "Identity, routing IDs, consent, encrypted setup and derived chart facts are stored "
    "locally. Queued inputs/replies and prepared/finalize work are encrypted and wiped on "
    "completion/final failure; unfinished payloads and date/record clarification/focus expire "
    "within 24 hours, with cleanup when workers run. Queue metadata remains. Before consent, "
    "ordinary text is discarded; explicit inspection/erasure controls use the queue.\n\n"
    "Readings use SecondContext and its AI provider. Filtered chat, replies and retrieved "
    "context are retained there. Obvious secrets and recognized birth clauses/continuations "
    "stay local; filtering is limited. Raw saved birth profiles/onboarding are not sent. "
    "Calculated facts and blocked drafts may be retained. Backups, retired indexes, upstream "
    "providers and Telegram have separate lifecycles.\n\n"
    "By choosing “I'm 18+ and agree”, you confirm you are at least 18 and consent to this data "
    "use.\n\n"
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
                from oria_engine.context.projections import LinkedContext
                from oria_engine.context.second_context import SecondContextProvider
                from oria_engine.domain.memory import directive

                request = directive(message.text)
                context = self.onboarding.context
                if (
                    context is not None
                    and isinstance(context.provider, SecondContextProvider)
                    and context.provider.knowledge_enabled
                    and (command in {"memory", "memories"} or request and request.action == "read")
                ):
                    linked = LinkedContext(
                        session, self.onboarding.encryption, self.policy_version, context.provider
                    )
                    recalled = await linked.inspect(user_id, message.text)
                    if recalled and len((memory_reply + recalled).encode("utf-16-le")) // 2 < 4050:
                        memory_reply += "\n\n" + recalled
                    if any(row.pending and row.deleted for row in await linked.repo.rows(user_id)):
                        memory_reply += "\nSecondContext removal is still pending."
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
