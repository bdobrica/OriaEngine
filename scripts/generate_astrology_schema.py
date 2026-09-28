"""Regenerate the published v1 schema or check for drift with --check."""

import json
import sys
from pathlib import Path

from oria_engine.astrology.contracts import NatalRequest, NatalResult

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
