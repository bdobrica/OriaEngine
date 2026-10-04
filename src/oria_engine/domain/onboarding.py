"""Deterministic, consent-gated onboarding. No Telegram types or model calls."""

from unicodedata import normalize
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from oria_engine.astrology.client import AstrologyClient, AstrologyUnavailable
from oria_engine.context.contracts import ConversationRequest
from oria_engine.context.service import ConversationContext
from oria_engine.db.astrology_profiles import AstrologyProfileRepository
from oria_engine.db.birth_profiles import BirthProfileRepository, ConsentRequiredError
from oria_engine.db.onboarding import OnboardingRepository
from oria_engine.db.repositories import ConsentRepository, UserRepository, UserUnavailableError
from oria_engine.domain.active import prepare_active, render_active
from oria_engine.domain.birth_profile import BirthPlace
from oria_engine.domain.birth_time import birth_zone, utc_candidates
from oria_engine.domain.channel import ChannelButton, ChannelMessage
from oria_engine.domain.consent import ConsentReply
from oria_engine.domain.consent import OnboardingState as State
from oria_engine.domain.onboarding_data import OnboardingDraft, parse_birth_date, parse_birth_time
from oria_engine.domain.places import PlaceResolutionUnavailable, PlaceResolver, TooManyPlaces
from oria_engine.domain.policy import PRIVACY_REPLY
from oria_engine.observability import count
from oria_engine.privacy.encryption import ProfileEncryption
from oria_engine.privacy.messages import private_active_input

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
    if draft.birth_local_time is not None:
        try:
            candidates = utc_candidates(
                draft.birth_date, draft.birth_local_time, draft.birth_place.timezone
            )
        except ValueError:
            return State.BIRTH_TIME_CLARIFICATION
        if not candidates or (len(candidates) == 2 and draft.birth_time_occurrence is None):
            return State.BIRTH_TIME_CLARIFICATION
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
    elif state == State.BIRTH_TIME_CLARIFICATION:
        assert draft.birth_date is not None and draft.birth_local_time is not None
        assert draft.birth_place is not None
        try:
            instants = utc_candidates(
                draft.birth_date, draft.birth_local_time, draft.birth_place.timezone
            )
        except ValueError:
            instants = ()
        if len(instants) == 2:
            text = (
                "That local time occurred twice when clocks changed. Which occurrence "
                "matches your birth record? If you cannot tell, choose Unknown time."
            )
            zone = birth_zone(draft.birth_place.timezone)
            buttons = tuple(
                button(
                    f"{label} (UTC{instant.astimezone(zone):%z})",
                    f"occurrence-{i}",
                )
                for i, (label, instant) in enumerate(
                    zip(("First", "Second"), instants, strict=True)
                )
            )
        else:
            text = (
                "That local date/time cannot be converted safely in the selected timezone "
                "(it may fall in a clock-change gap). Please check the date, time and place, "
                "or choose Unknown time. I won't shift the time automatically."
            )
        buttons += (
            button("Edit date", "edit-date"),
            button("Edit time", "edit-time"),
            button("Edit place", "edit-place"),
            button("Unknown time", "unknown"),
        )
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
            "Confirm to calculate your chart. Unknown time limits the available facts."
        )
        instant = draft.profile().utc_instant()
        if instant is not None:
            text += f"\nUTC: {instant.isoformat()} (time accuracy: {draft.birth_time_accuracy})"
        buttons = (
            button("Confirm profile", "confirm"),
            button("Edit date", "edit-date"),
            button("Edit time", "edit-time"),
            button("Edit place", "edit-place"),
        )
    return ConsentReply(state, f"{prefix}\n\n{text}" if prefix else text, buttons)


class OnboardingFlow:
    def __init__(
        self,
        encryption: ProfileEncryption,
        policy_version: str,
        resolver: PlaceResolver,
        astrology: AstrologyClient | None = None,
        context: ConversationContext | None = None,
    ) -> None:
        self.encryption = encryption
        self.policy_version = policy_version
        self.resolver = resolver
        self.astrology = astrology
        self.context = context

    async def inspect_profile(self, session: AsyncSession, user_id: UUID) -> ConsentReply:
        """Owner-only inspection, including after withdrawal; never calculate or mutate."""
        if await UserRepository(session).get(user_id, for_update=True) is None:
            raise UserUnavailableError("User unavailable")
        consents = ConsentRepository(session)
        current = await consents.current(user_id, self.policy_version)
        latest = await consents.latest(user_id)
        profile = await BirthProfileRepository(
            session, self.encryption, policy_version=self.policy_version
        ).get(user_id)
        draft = await OnboardingRepository(session, self.encryption, self.policy_version).get(
            user_id
        )
        result = await AstrologyProfileRepository(session, policy_version=self.policy_version).get(
            user_id
        )
        state = (
            resolve_state(draft, profile_exists=profile is not None)
            if current
            else State.CONSENT_REQUIRED
        )
        if current and result is not None:
            state = State.ACTIVE
        elif (
            latest
            and latest.policy_version == self.policy_version
            and latest.status in {"declined", "revoked"}
        ):
            state = State.CLOSED
        sections = [f"Current policy: {self.policy_version}"]
        sections.append(
            f"Latest consent: {latest.status} (policy {latest.policy_version})"
            if latest
            else "Consent: not recorded"
        )
        for label, data in (("Confirmed birth profile", profile), ("Unconfirmed draft", draft)):
            if data is None:
                continue
            time_text = data.birth_local_time.isoformat() if data.birth_local_time else "not set"
            if data.birth_time_accuracy == "unknown":
                time_text = "unknown"
            lines = [
                label,
                f"Date: {data.birth_date or 'not set'}",
                f"Local time: {time_text} ({data.birth_time_accuracy or 'not set'})",
            ]
            place = data.birth_place
            if place is not None:
                lines += [
                    f"Place: {place.display_name}",
                    f"City: {place.city}; region: {place.region or 'not set'}; "
                    f"country: {place.country_code}",
                    f"Coordinates: {place.latitude}, {place.longitude}",
                    f"Timezone: {place.timezone}",
                ]
            else:
                lines.append("Place: not selected")
            if data.birth_time_occurrence is not None:
                lines.append(
                    "Clock-change occurrence: "
                    + ("first" if data.birth_time_occurrence == 0 else "second")
                )
            sections.append("\n".join(lines))
        if profile is None:
            sections.append(
                "No confirmed birth profile saved. Use /start to begin or resume setup."
            )
        if result is None:
            sections.append(
                "Natal chart: not current/available. Consent and a confirmed profile are "
                "required; use /retry_profile after setup."
            )
        elif result.birth_time_accuracy == "unknown":
            sections.append(
                "Natal chart: current unknown-time result; positions, houses, angles "
                "and aspects unavailable."
            )
        else:
            sections.append(
                "Natal chart: current."
                + (
                    " Approximate birth time; chart facts are uncertain."
                    if result.birth_time_accuracy == "approximate"
                    else ""
                )
                + (" Houses and angles unavailable." if not result.availability.houses else "")
            )
        sections.append(
            "Use /edit_profile to correct date, time or place after consent. Selecting a place "
            "updates its coordinates and timezone. Use /privacy for storage and consent controls."
        )
        return ConsentReply(state, "\n\n".join(sections))

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
            # Active questions need only a valid derived cache, never decrypted birth inputs.
            if (
                self.astrology is not None
                and command is None
                and message.callback_data is None
                and message.text.strip()
                and not message.text.startswith("/")
            ):
                natal = await AstrologyProfileRepository(
                    session, policy_version=self.policy_version
                ).get(user_id)
                if natal is not None:
                    if self.context is not None and private_active_input(message.text):
                        count("policy_input_block")
                        return ConsentReply(State.ACTIVE, PRIVACY_REPLY)
                    try:
                        facts = await prepare_active(
                            message.text,
                            received_at=message.received_at,
                            natal=natal,
                            client=self.astrology,
                        )
                        if (
                            self.context is not None
                            and facts.intent.kind != "unsupported_high_stakes"
                            and facts.intent.kind != "clarify_date"
                        ):
                            response = await self.context.respond(
                                session,
                                user_id,
                                ConversationRequest(
                                    filtered_message=message.text,
                                    goal=facts.intent.kind,
                                    natal_facts=natal,
                                    transit_facts=facts.transits,
                                ),
                            )
                            return ConsentReply(State.ACTIVE, response.text)
                        if facts.intent.kind == "unsupported_high_stakes":
                            count("policy_high_stakes")
                        return ConsentReply(State.ACTIVE, render_active(facts))
                    except AstrologyUnavailable:
                        if self.context is not None:
                            raise  # The durable worker owns bounded retries.
                        return ConsentReply(
                            State.ACTIVE,
                            "Transit calculation is temporarily unavailable. "
                            "Please resend your question to retry. "
                            "Your natal chart is still saved.",
                        )
            profile = await profiles.get(user_id)
            if profile is not None:
                needs_clarification = False
                try:
                    profile.utc_instant()
                except ValueError:
                    needs_clarification = True
                if command in {"edit_profile", "edit-profile"} or needs_clarification:
                    draft = OnboardingDraft.model_validate(
                        {
                            **profile.model_dump(exclude={"schema_version"}),
                            "consent_id": consent.id,
                        }
                    )
                    await drafts.save(user_id, draft)
                    return reply_for(draft)
                return await self.saved_reply(
                    session, user_id, profiles, calculate=command == "retry_profile"
                )
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
                return await self.saved_reply(session, user_id, profiles, calculate=True)
            editable = state in {State.PROFILE_CONFIRMATION, State.BIRTH_TIME_CLARIFICATION}
            if editable and action == "edit-date":
                draft = draft.model_copy(update={"birth_date": None})
            elif editable and action == "edit-time":
                draft = draft.model_copy(
                    update={"birth_local_time": None, "birth_time_accuracy": None}
                )
            elif (editable or state == State.BIRTH_PLACE_CONFIRMATION) and action == "edit-place":
                draft = draft.model_copy(update={"birth_place": None, "candidates": ()})
            elif (
                state in {State.BIRTH_TIME_REQUIRED, State.BIRTH_TIME_CLARIFICATION}
                and action == "unknown"
            ):
                draft = draft.model_copy(
                    update={"birth_local_time": None, "birth_time_accuracy": "unknown"}
                )
            elif state == State.BIRTH_TIME_CLARIFICATION and action in {
                "occurrence-0",
                "occurrence-1",
            }:
                assert draft.birth_date is not None and draft.birth_local_time is not None
                assert draft.birth_place is not None
                try:
                    instants = utc_candidates(
                        draft.birth_date, draft.birth_local_time, draft.birth_place.timezone
                    )
                except ValueError:
                    return reply_for(draft)
                if len(instants) != 2:
                    return reply_for(draft)
                draft = draft.model_copy(update={"birth_time_occurrence": int(action[-1])})
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
                    parts = [normalize("NFC", part.strip()) for part in text.split(",")]
                    if len(parts) != 2 or any(
                        not 1 <= len(part) <= 128
                        or not any(c.isalpha() for c in part)
                        or not all(c.isalpha() or c in " -'.’" for c in part)
                        for part in parts
                    ):
                        return reply_for(draft, prefix="Use city, country only.")
                    try:
                        candidates = await self.resolver.resolve(*parts)
                    except TooManyPlaces:
                        return reply_for(draft, prefix="Many matches. Use city - region, country.")
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
                        return reply_for(
                            draft,
                            prefix=(
                                "No matching place in the local dataset. "
                                "Check city and country (or ISO country code)."
                            ),
                        )
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
        if callback is None or action not in {"occurrence-0", "occurrence-1"}:
            draft = draft.model_copy(update={"birth_time_occurrence": None})
        await drafts.save(user_id, draft)
        return reply_for(draft)

    async def saved_reply(
        self,
        session: AsyncSession,
        user_id: UUID,
        profiles: BirthProfileRepository,
        *,
        calculate: bool,
    ) -> ConsentReply:
        if self.astrology is None:
            return ConsentReply(State.COMPUTING_PROFILE, SAVED_TEXT)
        derived = AstrologyProfileRepository(session, policy_version=self.policy_version)
        result = await derived.get(user_id)
        if result is None and calculate:
            try:
                result = await derived.calculate(user_id, profiles, self.astrology)
            except AstrologyUnavailable:
                return ConsentReply(
                    State.COMPUTING_PROFILE,
                    "Your encrypted birth profile is saved. Chart calculation failed. "
                    "Use /retry_profile to try again, or /edit_profile to correct the details. "
                    "Supported birth years are 1800–2399.",
                )
        if result is None:
            return ConsentReply(
                State.COMPUTING_PROFILE,
                "Your birth profile is saved; a current derived chart is not available. "
                "Use /retry_profile to calculate it or /edit_profile to correct your details.",
            )
        if result.birth_time_accuracy == "unknown":
            text = (
                "Your profile is active. The saved calculation records unknown time; "
                "planetary positions, houses, angles and aspects are unavailable."
            )
        else:
            text = "Your profile is active. A valid derived natal chart is saved."
            if result.birth_time_accuracy == "approximate":
                text += " Chart facts use your approximate birth time."
            if not result.availability.houses:
                text += " Houses and angles are unavailable for this calculation."
        return ConsentReply(State.ACTIVE, text + " Use /edit_profile to change birth details.")
