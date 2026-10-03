"""Optional live review using only synthetic facts; requires local SecondContext.

Run with `uv run python scripts/evaluate_conversation.py`. Reads normal SecondContext
settings. Prints synthetic replies for human review, never credentials or raw profiles.
Creates disposable synthetic subjects; no existing account is touched. Authenticated
purge is attempted afterwards; the report states whether cleanup succeeded.
"""

import asyncio
import json
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

from astrology_mcp.engine import calculate, calculate_transits

from oria_engine.astrology.contracts import NatalRequest
from oria_engine.astrology.transits import TransitRequest
from oria_engine.config import Settings
from oria_engine.context.contracts import ContextScope, ContextUnavailable, ConversationRequest
from oria_engine.context.second_context import SecondContextProvider
from oria_engine.domain.policy import PRIVACY_REPLY, SAFETY_REPLY, guard_reply, is_high_stakes
from oria_engine.privacy.messages import private_active_input


async def main() -> None:
    settings = Settings()
    provider = SecondContextProvider(settings)
    fixtures = json.loads(Path("tests/unit/fixtures/oria-tone.json").read_text())
    subjects = []
    try:
        for fixture in fixtures:
            question = fixture["user"]
            if private_active_input(question) or is_high_stakes(question):
                text = PRIVACY_REPLY if private_active_input(question) else SAFETY_REPLY
                print(json.dumps({"case": fixture["id"], "path": "local", "reply": text}))
                continue
            accuracy = {"unknown_time": "unknown", "approximate_time": "approximate"}.get(
                fixture["id"], "exact"
            )
            natal = calculate(
                NatalRequest.model_validate(
                    {
                        "birth_time_accuracy": accuracy,
                        "local_birth_date": date(1990, 4, 13) if accuracy == "unknown" else None,
                        "timestamp_utc": None
                        if accuracy == "unknown"
                        else datetime(1990, 4, 13, 1, 42, tzinfo=UTC),
                        "latitude": 46.77,
                        "longitude": 23.59,
                    }
                )
            )
            transit = (
                calculate_transits(
                    TransitRequest.from_natal(natal, datetime(2026, 10, 2, 12, tzinfo=UTC))
                )
                if fixture["id"] == "transit_snapshot"
                else None
            )
            scope = ContextScope(user_id=uuid4(), session_id=uuid4())
            subjects.append(scope.user_id)
            request = ConversationRequest(
                filtered_message=question,
                natal_facts=natal,
                transit_facts=transit,
                goal="transits_for_date" if transit else "natal_explanation",
            )
            try:
                draft = await provider.respond(scope, request)
                reply = guard_reply(draft.text)
                print(
                    json.dumps(
                        {
                            "case": fixture["id"],
                            "path": "live",
                            "draft": draft.text,
                            "reply": reply,
                            "replaced": reply != draft.text,
                        }
                    ),
                    flush=True,
                )
            except ContextUnavailable:
                print(json.dumps({"case": fixture["id"], "path": "unavailable"}), flush=True)
    finally:
        for subject in subjects:
            try:
                await provider.purge(subject)
                print('{"cleanup": "completed"}')
            except ContextUnavailable:
                print('{"cleanup": "unavailable; synthetic transcript remains"}')
        await provider.aclose()


if __name__ == "__main__":
    asyncio.run(main())
