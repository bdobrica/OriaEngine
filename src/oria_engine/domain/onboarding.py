"""Deterministic, consent-gated onboarding. No Telegram types or model calls."""

from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from oria_engine.db.birth_profiles import BirthProfileRepository, ConsentRequiredError
from oria_engine.db.onboarding import OnboardingRepository
from oria_engine.db.repositories import ConsentRepository, UserRepository, UserUnavailableError
from oria_engine.domain.birth_profile import BirthPlace
from oria_engine.domain.channel import ChannelButton, ChannelMessage
from oria_engine.domain.consent import ConsentReply
from oria_engine.domain.consent import OnboardingState as State
from oria_engine.domain.onboarding_data import OnboardingDraft, parse_birth_date, parse_birth_time
from oria_engine.domain.places import PlaceResolutionUnavailable, PlaceResolver
from oria_engine.privacy.encryption import ProfileEncryption

DATE_PROMPT = "What is your birth date? Use YYYY-MM-DD or DD Mon YYYY (for example, 13 Apr 1990)."
TIME_PROMPT = (
    "What is your local birth time? Use 24-hour HH:MM for exact time, "
    "approximate HH:MM, or choose Unknown."
)
PLACE_PROMPT = "What is your birthplace? Send city, country only; no address or other details."
SAVED_TEXT = (
    "Your confirmed birth profile is encrypted and saved. Chart calculation is not available "
    "yet, so your profile is waiting for calculation. Use /privacy to review consent."
)


def resolve_state(draft: OnboardingDraft | None, *, profile_exists: bool = False) -> State:
    if draft is None:
        return State.COMPUTING_PROFILE if profile_exists else State.BIRTH_DATE_REQUIRED
    if draft.birth_date is None:
        return State.BIRTH_DATE_REQUIRED
    if draft.birth_time_accuracy is None:
        return State.BIRTH_TIME_REQUIRED
    if draft.birth_place is None:
        return State.BIRTH_PLACE_CONFIRMATION if draft.candidates else State.BIRTH_PLACE_REQUIRED
    return State.PROFILE_CONFIRMATION


def reply_for(draft: OnboardingDraft, *, prefix: str = "") -> ConsentReply:
    state = resolve_state(draft)

    def button(label: str, action: str) -> ChannelButton:
        return ChannelButton(label, f"onboard:{draft.token}:{action}")

    buttons: tuple[ChannelButton, ...] = ()
    if state == State.BIRTH_DATE_REQUIRED:
        text = DATE_PROMPT
    elif state == State.BIRTH_TIME_REQUIRED:
        text = TIME_PROMPT
        buttons = (button("Unknown time", "unknown"),)
    elif state == State.BIRTH_PLACE_REQUIRED:
        text = PLACE_PROMPT
    elif state == State.BIRTH_PLACE_CONFIRMATION:
        text = "Select your birthplace, or choose another city:"
        buttons = tuple(
            button(f"{p.display_name} ({p.region or p.city}, {p.country_code})", f"place-{i}")
            for i, p in enumerate(draft.candidates)
        ) + (button("Another city", "edit-place"),)
    else:
        time_text = (
            "unknown"
            if draft.birth_local_time is None
            else f"{draft.birth_local_time:%H:%M} ({draft.birth_time_accuracy})"
        )
        assert draft.birth_place is not None
        text = (
            f"Please confirm your birth profile:\nDate: {draft.birth_date}\n"
            f"Local time: {time_text}\nPlace: {draft.birth_place.display_name}\n"
            f"Region: {draft.birth_place.region or draft.birth_place.city}, "
            f"{draft.birth_place.country_code}\nTimezone: {draft.birth_place.timezone}\n"
            "Chart calculation will follow when available."
        )
        buttons = (
            button("Confirm profile", "confirm"),
            button("Edit date", "edit-date"),
            button("Edit time", "edit-time"),
            button("Edit place", "edit-place"),
        )
    return ConsentReply(state, f"{prefix}\n\n{text}" if prefix else text, buttons)


class OnboardingFlow:
    def __init__(
        self, encryption: ProfileEncryption, policy_version: str, resolver: PlaceResolver
    ) -> None:
        self.encryption = encryption
        self.policy_version = policy_version
        self.resolver = resolver

    async def handle(
        self,
        session: AsyncSession,
        user_id: UUID,
        message: ChannelMessage,
        *,
        command: str | None = None,
    ) -> ConsentReply:
        if await UserRepository(session).get(user_id, for_update=True) is None:
            raise UserUnavailableError("User unavailable")
        consent = await ConsentRepository(session).current(user_id, self.policy_version)
        if consent is None:
            raise ConsentRequiredError("Current consent required")
        drafts = OnboardingRepository(session, self.encryption, self.policy_version)
        profiles = BirthProfileRepository(
            session, self.encryption, policy_version=self.policy_version
        )
        draft = await drafts.get(user_id)
        if draft is None:
            if await profiles.get(user_id) is not None:
                return ConsentReply(State.COMPUTING_PROFILE, SAVED_TEXT)
            draft = OnboardingDraft(consent_id=consent.id)
            await drafts.save(user_id, draft)
        elif draft.consent_id != consent.id:
            # Fresh consent invalidates buttons from an earlier acceptance without losing fields.
            draft = draft.model_copy(update={"consent_id": consent.id, "token": uuid4().hex})
            await drafts.save(user_id, draft)

        if command is not None or message.text.startswith("/"):
            return reply_for(draft)
        state = resolve_state(draft)
        callback = message.callback_data
        if callback is not None:
            if not callback.startswith(f"onboard:{draft.token}:"):
                return reply_for(draft)
            action = callback.removeprefix(f"onboard:{draft.token}:")
            if state == State.PROFILE_CONFIRMATION and action == "confirm":
                await profiles.save(user_id, draft.profile())
                await drafts.clear(user_id)
                return ConsentReply(State.COMPUTING_PROFILE, SAVED_TEXT)
            if state == State.PROFILE_CONFIRMATION and action == "edit-date":
                draft = draft.model_copy(update={"birth_date": None})
            elif state == State.PROFILE_CONFIRMATION and action == "edit-time":
                draft = draft.model_copy(
                    update={"birth_local_time": None, "birth_time_accuracy": None}
                )
            elif (
                state in {State.PROFILE_CONFIRMATION, State.BIRTH_PLACE_CONFIRMATION}
                and action == "edit-place"
            ):
                draft = draft.model_copy(update={"birth_place": None, "candidates": ()})
            elif state == State.BIRTH_TIME_REQUIRED and action == "unknown":
                draft = draft.model_copy(
                    update={"birth_local_time": None, "birth_time_accuracy": "unknown"}
                )
            elif state == State.BIRTH_PLACE_CONFIRMATION and action in {
                f"place-{i}" for i in range(len(draft.candidates))
            }:
                draft = draft.model_copy(
                    update={
                        "birth_place": draft.candidates[int(action.removeprefix("place-"))],
                        "candidates": (),
                    }
                )
            else:
                return reply_for(draft)
        else:
            text = message.text.strip()
            try:
                if state == State.BIRTH_DATE_REQUIRED:
                    draft = draft.model_copy(update={"birth_date": parse_birth_date(text)})
                elif state == State.BIRTH_TIME_REQUIRED:
                    local_time, accuracy = parse_birth_time(text)
                    draft = draft.model_copy(
                        update={"birth_local_time": local_time, "birth_time_accuracy": accuracy}
                    )
                elif state == State.BIRTH_PLACE_REQUIRED:
                    parts = [part.strip() for part in text.split(",")]
                    if len(parts) != 2 or any(
                        not 1 <= len(part) <= 128
                        or not any(c.isalpha() for c in part)
                        or not all(c.isalpha() or c in " -'." for c in part)
                        for part in parts
                    ):
                        return reply_for(draft, prefix="Use city, country only.")
                    try:
                        candidates = await self.resolver.resolve(*parts)
                    except PlaceResolutionUnavailable:
                        return reply_for(
                            draft,
                            prefix=(
                                "Local place lookup is not available in this demo yet. "
                                "Your date/time progress is saved; "
                                "please try again once local place lookup is available."
                            ),
                        )
                    if not candidates:
                        return reply_for(draft, prefix="No matching place. Check city and country.")
                    # Validate and bound resolver output before storing or presenting it.
                    draft = OnboardingDraft.model_validate(
                        {
                            **draft.model_dump(),
                            "candidates": tuple(BirthPlace.model_validate(p) for p in candidates),
                        }
                    )
                else:
                    return reply_for(draft, prefix="Please use the buttons to confirm or edit.")
            except ValueError:
                return reply_for(
                    draft, prefix="I couldn't use that entry. Please try the requested format."
                )
        draft = draft.model_copy(update={"token": uuid4().hex})
        await drafts.save(user_id, draft)
        return reply_for(draft)
