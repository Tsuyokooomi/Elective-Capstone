"""Output filter (Phase 5B): checks the model's answer before the user sees it.

The input guardrails cannot catch everything, so the reply is checked too:
- prompt_leak: the reply repeats lines of our own system prompts
- secret: the reply contains a token, a password hash, an API key or one of our configured secrets
- pii: the reply repeats a card number, a government ID or a one-time code
- asks_for_secret: the reply asks the user to send a password or code to the assistant

Only replies written by the LLM are checked. Fixed messages from our own code are trusted."""
import re
from functools import lru_cache

from app.config import settings
from app.guardrails.pii import redact_pii
from app.rag.prompts import (
    ASKS_SECRET_MESSAGE,
    CLASSIFIER_SYSTEM_PROMPT_HEAD,
    OUTPUT_BLOCKED_MESSAGE,
    RAG_SYSTEM_PROMPT,
)

SECRET_PATTERNS = [
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),     # a JWT (login or reset token)
    re.compile(r"pbkdf2_sha256\$\d+\$[0-9a-f]+\$[0-9a-f]+"),                          # one of our password hashes
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),                                           # an OpenAI-style API key
    re.compile(r"reset_token=[A-Za-z0-9._-]+"),                                       # a password reset link
]

ASKS_SECRET = re.compile(
    r"\b(?:send|tell|give|share|provide|type|paste|reply with|enter)\b.{0,20}\b(?:me|us|here|in (?:this )?chat)\b"
    r".{0,30}\b(?:your |the )?(?:current |old |new )?(?:password|passcode|backup code|otp|mfa code|verification code)\b",
    re.IGNORECASE | re.DOTALL,
)


def _squash(text: str) -> str:
    return " ".join(text.lower().split())


@lru_cache
def _prompt_fragments() -> tuple[str, ...]:
    """Sentences of our system prompts that are long enough to be unmistakable."""
    from app.rag.prompts import build_classifier_prompt   # imported here: the intent table is built at import time
    fragments = []
    for prompt in (RAG_SYSTEM_PROMPT, CLASSIFIER_SYSTEM_PROMPT_HEAD, build_classifier_prompt()):
        for line in prompt.splitlines():
            for sentence in re.split(r"(?<=[.:?!])\s+", line):
                sentence = _squash(sentence)
                if len(sentence) >= 45:
                    fragments.append(sentence)
    return tuple(dict.fromkeys(fragments))


def _configured_secrets() -> list[str]:
    values = [settings.secret_key, settings.webhook_secret, settings.openai_api_key]
    return [v for v in values if v and len(v) >= 8]


def filter_output(text: str) -> tuple[str, list[str]]:
    """Return (safe text, flags). No flags means the text is unchanged."""
    flags: list[str] = []
    squashed = _squash(text)

    if any(fragment in squashed for fragment in _prompt_fragments()):
        return OUTPUT_BLOCKED_MESSAGE, ["prompt_leak"]

    if ASKS_SECRET.search(text):
        return ASKS_SECRET_MESSAGE, ["asks_for_secret"]

    cleaned = text
    for pattern in SECRET_PATTERNS:
        cleaned = pattern.sub("[REDACTED]", cleaned)
    for value in _configured_secrets():
        cleaned = cleaned.replace(value, "[REDACTED]")
    if cleaned != text:
        flags.append("secret")

    cleaned, found = redact_pii(cleaned, kinds=("CARD", "GOV_ID", "OTP"))
    if found:
        flags.append("pii")
    return cleaned, flags
