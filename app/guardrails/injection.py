"""Prompt injection check (Phase 5B).

Runs before any LLM call. Text is first cleaned (see text.py), then matched against rules grouped
by what the attacker is trying to do. The rules cover English and Filipino. A rule match blocks the
message, so the rules are written to catch attacks and not ordinary IT questions such as
"System: Windows 11" or "I cannot sign in without MFA"."""
import re

from app.guardrails.text import views

_DIRECTIVE = r"(?:the user|you\b|ignore|new\b|override|from now|your\b|this is|reset|list|show|grant|disable|enable|allow|assistant)"
_NOUN_RULES = r"(?:instructions?|rules|prompts?|guidelines|polic(?:y|ies)|restrictions|guardrails?|directives?|programming|training)"
_NOUN_FIL = r"(?:utos|instruksyon(?:es)?|instructions?|patakaran|rules?|bilin|panuto|alituntunin)"
_SECRET_THINGS = r"(?:api keys?|secret keys?|signing keys?|private keys?|\.env|environment variables|database (?:contents?|dump|credentials|password)|connection strings?)"
_GIVE = r"(?:show|reveal|print|give|send|tell|share|leak|dump|list|export)"

RULES = [
    # 1. Tell the model to drop its rules
    ("override_instructions", rf"\b(?:ignore|disregard|forget|override|overrule)\b.{{0,30}}\b(?:previous|prior|above|earlier|preceding|all|any|your|these|those|system|safety|security)\b.{{0,30}}\b{_NOUN_RULES}\b"),
    ("override_instructions", rf"\b(?:kalimutan|kalimutin|balewalain|ignorahin|i-?ignore)\b.{{0,40}}\b{_NOUN_FIL}\b"),
    ("override_instructions", rf"\b(?:huwag|wag)(?: mong)? sundin\b.{{0,30}}\b{_NOUN_FIL}\b"),
    # 2. Make it reveal its prompt
    ("reveal_prompt", r"\b(?:show|reveal|print|repeat|display|output|leak|tell|give|share|dump|recite|summari[sz]e|translate)\b.{0,40}\b(?:system prompt|system message|developer message|hidden prompt|initial prompt|the prompt above|your (?:initial |original |hidden |secret |internal )?(?:instructions|prompt|rules|guidelines|configuration))\b"),
    ("reveal_prompt", r"\bwhat (?:is|are|were) your (?:system |initial |original |hidden )?(?:prompt|instructions|rules)\b"),
    ("reveal_prompt", r"\b(?:ipakita|sabihin|ibigay|i-?print)\b.{0,30}\b(?:system prompt|prompt mo|instruksyon mo|panuto mo|utos mo|bilin mo|patakaran mo)\b"),
    # 3. Give it a new role
    ("role_override", r"\byou are now\b.{0,25}\b(?:admin|administrator|developer|dan|jailbroken|jailbreak|unrestricted|root|evil|uncensored)\b"),
    ("role_override", r"\b(?:act|behave|respond) (?:as|like)\b.{0,25}\b(?:admin|administrator|root|developer|unrestricted|uncensored|jailbroken|dan|hacker|system|superuser)\b"),
    ("role_override", r"\bpretend\b.{0,15}\b(?:to be|you are|you're|that you)\b.{0,30}\b(?:admin|administrator|root|developer|unrestricted|uncensored|human|different|another)\b"),
    ("role_override", r"\bfrom now on\b.{0,40}\b(?:you (?:are|will|must|can|should)|ignore|no (?:rules|restrictions|limits))\b"),
    ("role_override", r"\b(?:developer|admin|administrator|root|god|debug|jailbreak|sudo|dan|maintenance) mode\b"),
    ("role_override", r"\bdo anything now\b"),
    ("role_override", r"\b(?:ikaw na ngayon|ikaw ay|maging)\b.{0,20}\b(?:admin|administrator|developer|walang (?:limitasyon|patakaran))\b"),
    ("role_override", r"\bwala(?:ng| nang)? (?:limitasyon|patakaran|rules|restrictions)\b"),
    # 4. Fake system messages and chat-template markers
    ("fake_system", rf"(?m)^\s*(?:system|developer)\s*:\s*{_DIRECTIVE}"),
    ("fake_system", r"\[\s*/?\s*(?:system|inst|sys)\s*\]"),
    ("fake_system", r"<\s*/?\s*(?:system|im_start|im_end|instructions?)\s*>"),
    ("fake_system", r"<\|[^|]{0,30}\|>"),
    ("fake_system", r"\bnew instructions?\s*:"),
    ("fake_system", r"\bend of (?:the )?(?:system )?(?:prompt|instructions|context)\b"),
    ("fake_system", r"(?m)^#{2,}\s*(?:system|instruction)"),
    # 5. Skip checks and confirmations
    ("security_bypass", r"\bbypass\b.{0,25}\b(?:mfa|2fa|authentication|auth|security|guardrails?|filters?|verification|confirmation|approval)\b"),
    ("security_bypass", r"\bwithout (?:any |the |your )?(?:confirmation|approval|verification|asking)\b"),
    ("security_bypass", r"\b(?:nang )?walang (?:confirmation|kumpirmasyon|verification)\b"),
    ("security_bypass", r"\b(?:disable|turn off|deactivate|remove)\b.{0,15}\b(?:guardrails?|safety (?:checks?|filters?|rules)|content filters?|audit log(?:ging|s)?)\b"),
    # 6. Steal secrets or data
    ("data_exfil", r"\bpassword hash(?:es)?\b"),
    ("data_exfil", rf"\b{_GIVE}\b.{{0,40}}\b{_SECRET_THINGS}\b"),
    ("data_exfil", rf"\b{_GIVE}\b.{{0,30}}\b(?:all|every|other|everyone'?s)\b.{{0,15}}\b(?:users?|employees?|accounts?)\b.{{0,25}}\b(?:passwords?|credentials|emails?|phone numbers?|data|records|tokens?)\b"),
    # 7. Database attacks
    ("sql_injection", r"\b(?:drop|truncate)\s+table\b"),
    ("sql_injection", r"\bunion\s+(?:all\s+)?select\b"),
    ("sql_injection", r"['\"]\s*or\s*['\"]?\s*1\s*['\"]?\s*=\s*['\"]?\s*1"),
    # 8. Hide the attack in an encoding
    ("encoded_payload", r"\b(?:decode|decrypt|deobfuscate|base64|rot13)\b.{0,40}\b(?:and|then)\b.{0,20}\b(?:follow|execute|run|obey|do)\b"),
]

_COMPILED = [(name, re.compile(pattern, re.DOTALL)) for name, pattern in RULES]


def detect_injection(text: str) -> str | None:
    """Return the name of the first rule group that matches, or None."""
    for view in views(text):
        for name, pattern in _COMPILED:
            if pattern.search(view):
                return name
    return None


def looks_like_injection(text: str) -> bool:
    return detect_injection(text) is not None
