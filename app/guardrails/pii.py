"""Basic PII redaction. Phase 5 will extend this."""
import re

PATTERNS = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("CARD", re.compile(r"(?<!\d)(?:\d[ -]?){13,16}(?!\d)")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+?63|0)9\d{2}[\s-]?\d{3}[\s-]?\d{4}(?!\d)")),
]


def redact_pii(text: str) -> tuple[str, list[str]]:
    """Return the text with PII replaced by tags, and the list of PII types found."""
    found = []
    for label, pattern in PATTERNS:
        if pattern.search(text):
            found.append(label)
            text = pattern.sub(f"[{label}]", text)
    return text, found
