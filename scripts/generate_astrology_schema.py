"""Regenerate the published v1 schema or check for drift with --check."""

import json
import sys
from pathlib import Path

from oria_engine.astrology.contracts import NatalRequest, NatalResult
from oria_engine.astrology.linked import schema_document
from oria_engine.astrology.transits import TransitRequest, TransitResult
from oria_engine.domain.readings import LinkedReading

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

linked_path = path.with_name("linked-v1.json")
linked_document = (
    json.dumps(
        schema_document() | {"context_facts": LinkedReading.model_json_schema()},
        indent=2,
        sort_keys=True,
    )
    + "\n"
)
if "--check" in sys.argv:
    if linked_path.read_text() != linked_document:
        raise SystemExit("Linked astrology schema drift; regenerate and review compatibility")
else:
    linked_path.write_text(linked_document)
