"""Public wire-shape agreement only; no assertion of provider runtime support."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2] / "contracts/second-context"
SCHEMA = json.loads((ROOT / "conversation-history-v1.schema.json").read_text())
CASES = json.loads((ROOT / "conversation-history-v1.examples.json").read_text())


def validator(definition):
    return Draft202012Validator({"$ref": f"#/$defs/{definition}", "$defs": SCHEMA["$defs"]})


def test_schema_is_valid_and_endpoint_objects_are_closed():
    Draft202012Validator.check_schema(SCHEMA)
    for definition in SCHEMA["$defs"].values():
        if definition.get("type") == "object":
            assert definition["additionalProperties"] is False
            assert set(definition["required"]) == set(definition["properties"])


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_provider_conformance_cases(case):
    assert validator(case["definition"]).is_valid(case["value"]) is case["valid"]


@pytest.mark.parametrize("field,limit", [("user_text", 4096), ("assistant_text", 16384)])
def test_local_text_limits_count_unicode_characters(field, limit):
    value = copy.deepcopy(next(case["value"] for case in CASES if case["name"] == "local"))
    value[field] = "🌙" * limit
    assert validator("FinalizeRequest").is_valid(value)
    value[field] += "x"
    assert not validator("FinalizeRequest").is_valid(value)


def test_local_sources_are_bounded_unique_and_revisioned():
    value = copy.deepcopy(next(case["value"] for case in CASES if case["name"] == "local_sources"))
    source = value["knowledge_refs"][0]
    source["revision"] = 0
    assert not validator("FinalizeRequest").is_valid(value)
    source["revision"] = 1
    value["knowledge_refs"] = [source, source]
    assert not validator("FinalizeRequest").is_valid(value)
    value["knowledge_refs"] = [{**source, "revision": n + 1} for n in range(21)]
    assert not validator("FinalizeRequest").is_valid(value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("session_id", "session\n"),
        ("session_id", "two sessions"),
        ("turn_id", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"),
        ("turn_id", "33333333-3333-4333-8333-333333333333\n"),
    ],
)
def test_managed_identifiers_are_exact_ascii(field, value):
    payload = copy.deepcopy(next(case["value"] for case in CASES if case["name"] == "local"))
    payload[field] = value
    assert not validator("FinalizeRequest").is_valid(payload)


def test_structural_validation_does_not_prove_receipt_identity():
    value = copy.deepcopy(
        next(case["value"] for case in CASES if case["name"] == "generated_receipt")
    )
    value["user"] = "oria:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    assert validator("Receipt").is_valid(value)
    # OCH2 must compare against the authenticated request, beyond schema validation.
    assert value["user"] != next(
        case["value"]["user"] for case in CASES if case["name"] == "generated"
    )
