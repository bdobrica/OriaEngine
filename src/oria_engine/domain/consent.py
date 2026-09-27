"""Deterministic consent decisions; no message/profile storage or model calls."""

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256

from oria_engine.db.repositories import ConsentRepository, SocialIdentityRepository
from oria_engine.db.session import Database
from oria_engine.domain.channel import HELP_TEXT, ChannelButton, ChannelMessage

# Initial copy uses the configured policy version (default 2026-09-01).
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
    "(/delete-me). In this demo, profile collection, editing and deletion are not available "
    "yet. Please don't send birth details. We currently store only internal identity, "
    "Telegram routing IDs and consent decisions; message text is not stored by OriaEngine. "
    "Telegram retains messages under its own policies. You can use Decline below to stop "
    "onboarding, including after accepting; this does not delete identity or consent history.\n\n"
    "This MVP is for adults aged 18 or older. By choosing 'I'm 18+ and agree', you confirm "
    "that you are at least 18 and consent to the described birth-data use."
)
ACCEPTED_TEXT = (
    "Your consent is recorded. The next step is your birth date, but profile setup "
    "is not available in this demo yet. Please don't send birth details. "
    "Use /privacy to review the policy or decline further onboarding."
)
DECLINED_TEXT = (
    "Onboarding is stopped. No birth profile has been collected. "
    "Your identity and consent decision remain stored. Use /start if you change your mind."
)


class OnboardingState(StrEnum):
    CONSENT_REQUIRED = "ConsentRequired"
    CLOSED = "Closed"
    BIRTH_DATE_REQUIRED = "BirthDateRequired"


@dataclass(frozen=True)
class ConsentReply:
    state: OnboardingState
    text: str
    buttons: tuple[ChannelButton, ...] = ()


class ConsentFlow:
    def __init__(self, database: Database, policy_version: str) -> None:
        self.database = database
        self.policy_version = policy_version
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
                else:
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
            return ConsentReply(state, HELP_TEXT if command == "help" else ACCEPTED_TEXT)
