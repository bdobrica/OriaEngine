"""Conservative English active-input gate; never logs or partially forwards a match."""

import re

from oria_engine.domain.policy import PII, normalize

SENSITIVE = re.compile(
    r"@|https?://|www\.|\b(?:born|birthday|birthplace|birth date|date of birth|"
    r"my name|i am named|i live|i work|my birth time)\b|"
    r"\b\d{1,2}:\d{2}\b|(?:\d[ ()+.-]*){7,}|"
    r"\b\d+\s+\w+\s+(?:street|road|avenue|lane|drive)\b"
)


def private_active_input(text: str) -> bool:
    """Reject obvious volunteered identifiers/birth values, with intentional false positives.

    One ISO transit date is excluded from numeric matching. Arbitrary unlabeled names,
    places, encoded values and other languages cannot be reliably detected lexically.
    """
    value = normalize(text)
    value = re.sub(r"(?<![\w-])\d{4}-\d{2}-\d{2}(?![\w-])", "[date]", value)
    return bool(PII.search(value) or SENSITIVE.search(value))
