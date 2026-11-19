"""Simple prompt injection check. Phase 5 will add stronger checks."""
import re

INJECTION_PATTERNS = [
    r"\bignore\b.{0,20}\b(previous|prior|above|earlier|all)\b.{0,20}\b(instructions?|rules|prompts?)\b",
    r"\b(forget|disregard)\b.{0,20}\b(rules|instructions|guidelines)\b",
    r"\b(show|reveal|print|repeat|display)\b.{0,30}\b(system prompt|your instructions|your prompt)\b",
    r"\byou are now\b.{0,20}\b(admin|developer|dan|jailbreak|unrestricted)\b",
    r"\b(admin|developer|root|god) mode\b",
    r"\bbypass\b.{0,20}\b(mfa|2fa|authentication|security|guardrails?)\b",
    r"^\s*system\s*:",
    r"\bpassword hash(es)?\b",
    r"\bwithout (any )?confirmation\b",
]


def looks_like_injection(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(p, lowered, re.DOTALL) for p in INJECTION_PATTERNS)
