"""Deterministic consent decisions gating optional encrypted onboarding; no model calls."""

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from typing import TYPE_CHECKING

from oria_engine.db.repositories import ConsentRepository, SocialIdentityRepository
from oria_engine.db.session import Database
from oria_engine.domain.channel import HELP_TEXT, ChannelButton, ChannelMessage

if TYPE_CHECKING:
    from oria_engine.domain.onboarding import OnboardingFlow

# Collection disclosure uses the configured policy version (default 2026-09-28.1).
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
    "The completed service will let you inspect your profile (/profile), correct it "
    "(/edit-profile), review privacy and withdraw consent (/privacy), and delete your data "
    "(/delete-me). In this demo, birth-profile collection, local place lookup, timezone "
    "clarification and editing during setup are available. Chart calculation, saved-profile "
    "controls and deletion are not available yet. "
    "We store internal identity, Telegram routing IDs, consent decisions and encrypted "
    "onboarding progress, including incomplete birth details. Confirmed profiles are encrypted. "
    "Send only the birth field requested; raw message text is not stored by OriaEngine. "
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
        return ConsentReply(state, f"Policy {self.policy_version}\n\n{DISCLAIMER}", self.buttons)

    async def handle(self, message: ChannelMessage, *, command: str | None = None) -> ConsentReply:
        async with self.database.transaction() as session:
            user = await SocialIdentityRepository(session).get_or_create_user_for_social_identity(
                provider=message.provider,
                provider_user_id=message.provider_user_id,
                provider_chat_id=message.provider_chat_id,
            )
            consents = ConsentRepository(session)
            stale_button = False
            if message.callback_data is not None:
                if message.callback_data == self.buttons[0].data:
                    await consents.accept(user.id, self.policy_version, message.provider)
                elif message.callback_data == self.buttons[1].data:
                    await consents.decline(user.id, self.policy_version, message.provider)
                elif not (
                    self.onboarding is not None and message.callback_data.startswith("onboard:")
                ):
                    # Old policy/unknown button: never convert it into a current decision.
                    stale_button = True
            latest = await consents.latest(user.id)
            if await consents.current(user.id, self.policy_version):
                state = OnboardingState.BIRTH_DATE_REQUIRED
            elif (
                latest
                and latest.policy_version == self.policy_version
                and latest.status in {"declined", "revoked"}
            ):
                state = OnboardingState.CLOSED
            else:
                state = OnboardingState.CONSENT_REQUIRED

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
                return await self.onboarding.handle(session, user.id, message, command=command)
            return ConsentReply(state, HELP_TEXT if command == "help" else ACCEPTED_TEXT)
