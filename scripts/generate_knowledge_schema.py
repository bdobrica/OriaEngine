"""Generate candidate knowledge contracts; --check fails on schema drift."""

import json
import sys
from pathlib import Path

from oria_engine.knowledge.contracts import schema_document

path = Path(__file__).resolve().parents[1] / "contracts/knowledge/v1.json"
document = json.dumps(schema_document(), indent=2, sort_keys=True) + "\n"
if "--check" in sys.argv:
    if path.read_text() != document:
        raise SystemExit("Knowledge schema drift; regenerate and review compatibility")
else:
    path.write_text(document)
