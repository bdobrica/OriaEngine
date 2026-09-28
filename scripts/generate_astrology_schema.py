"""Regenerate the published v1 schema or check for drift with --check."""

import json
import sys
from pathlib import Path

from oria_engine.astrology.contracts import NatalRequest, NatalResult
from oria_engine.astrology.transits import TransitRequest, TransitResult

path = Path(__file__).resolve().parents[1] / "contracts/astrology/v1.json"
document = (
    json.dumps(
        {"request": NatalRequest.model_json_schema(), "response": NatalResult.model_json_schema()},
        indent=2,
        sort_keys=True,
    )
    + "\n"
)
if "--check" in sys.argv:
    if path.read_text() != document:
        raise SystemExit("Astrology schema drift; regenerate and review compatibility")
else:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document)

transit_path = path.with_name("transits-v1.json")
transit_document = (
    json.dumps(
        {
            "request": TransitRequest.model_json_schema(),
            "response": TransitResult.model_json_schema(),
        },
        indent=2,
        sort_keys=True,
    )
    + "\n"
)
if "--check" in sys.argv:
    if transit_path.read_text() != transit_document:
        raise SystemExit("Transit schema drift; regenerate and review compatibility")
else:
    transit_path.write_text(transit_document)
