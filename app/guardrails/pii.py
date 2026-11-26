"""PII and secret redaction (Phase 5B).

Runs on every user message BEFORE it is stored or sent to an LLM. Covers: emails, card numbers,
Philippine mobile and landline numbers, SSS and TIN numbers, public IP addresses, passwords and
one-time codes typed into the chat. Names are NOT detected (that needs a language model).

Private IP addresses (10.x, 172.16-31.x, 192.168.x) are kept on purpose: they describe company
equipment, not people, and VPN troubleshooting needs them."""
import ipaddress
import re

_STOP_VALUES = {
    "not", "incorrect", "wrong", "expired", "locked", "working", "invalid", "blank", "empty", "the", "a", "an",
    "still", "always", "too", "being", "rejected", "correct", "changed", "reset", "forgotten", "missing",
    "required", "weak", "strong", "long", "short", "same", "different", "right", "fine", "ok", "okay", "there",
    "here", "it", "this", "that", "what", "why", "how", "and", "or", "but", "so", "because", "no", "never",
    "already", "just", "now", "only", "is", "was", "are", "has", "have", "didn't", "doesn't", "isn't", "wasn't",
    "can't", "cannot", "won't", "hindi", "ayaw", "mali", "wala", "sira", "expired.", "not.",
}

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
GOV_ID = [
    re.compile(r"(?<!\d)\d{2}-\d{7}-\d(?!\d)"),                       # SSS number
    re.compile(r"(?<!\d)\d{3}-\d{3}-\d{3}(?:-\d{3,5})?(?!\d)"),       # TIN
]
CARD = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,15}(?!\d)")   # 13-16 digits, no trailing space swallowed
MOBILE = re.compile(r"(?<!\d)(?:\+?63[\s-]?|0)9\d{2}[\s-]?\d{3}[\s-]?\d{4}(?!\d)")
LANDLINE = re.compile(r"(?<!\d)\(?0[2-8]\d?\)?[\s-]?\d{3,4}[\s-]\d{4}(?!\d)")
SECRET = re.compile(r"(?i)\b(password|passcode|passphrase|pwd|pin)\b(\s*(?:is|was|=|:)\s*|\s+ko\s+(?:ay\s+)?)(\S+)")
OTP = re.compile(
    r"(?i)((?:otp|totp)\b(?:\s+code)?|(?:mfa|2fa|verification|authenticator|authentication|backup|security|one[- ]time)"
    r"\s+(?:code|pin|passcode))(\s*(?:is|was|=|:)?\s*)(\d{4,8})\b"
)
IPV4 = re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?![\d.])")
_VERSION_CUE = re.compile(r"(?:version|ver\.?|build|v)\s*$", re.I)


def _secret(m: re.Match) -> str | None:
    if m.group(3).strip(".,;!?\"'").lower() in _STOP_VALUES:
        return None
    return f"{m.group(1)}{m.group(2)}[SECRET]"


def _otp(m: re.Match) -> str | None:
    return f"{m.group(1)}{m.group(2)}[OTP]"


def _public_ip(m: re.Match) -> str | None:
    if _VERSION_CUE.search(m.string[max(0, m.start() - 12):m.start()]):
        return None                       # "version 4.10.0.1" is a software version, not an address
    try:
        return "[IP]" if ipaddress.ip_address(m.group(0)).is_global else None
    except ValueError:
        return None


# (label, pattern, replacement text or function). A function returns None to leave the match alone.
RULES = [
    ("EMAIL", EMAIL, "[EMAIL]"),
    ("GOV_ID", GOV_ID[0], "[GOV_ID]"),
    ("GOV_ID", GOV_ID[1], "[GOV_ID]"),
    ("CARD", CARD, "[CARD]"),
    ("PHONE", MOBILE, "[PHONE]"),
    ("PHONE", LANDLINE, "[PHONE]"),
    ("SECRET", SECRET, _secret),
    ("OTP", OTP, _otp),
    ("IP", IPV4, _public_ip),
]


def redact_pii(text: str, kinds: tuple[str, ...] | None = None) -> tuple[str, list[str]]:
    """Return the text with PII replaced by tags, and the list of PII types found.
    kinds limits the check to some types (the output filter uses this)."""
    found: list[str] = []
    for label, pattern, replacement in RULES:
        if kinds is not None and label not in kinds:
            continue
        hit = False

        def swap(m: re.Match) -> str:
            nonlocal hit
            new = replacement(m) if callable(replacement) else replacement
            if new is None:
                return m.group(0)
            hit = True
            return new

        text = pattern.sub(swap, text)
        if hit and label not in found:
            found.append(label)
    return text, found


_TAG = re.compile(r"\[(?:EMAIL|PHONE|GOV_ID|CARD|SECRET|OTP)\]")


HIDDEN_TAG = re.compile(r"\[(?:EMAIL|PHONE|GOV_ID|CARD|SECRET|OTP|IP)\]")


def has_redaction_tag(text: str) -> bool:
    """True if the text contains a [PHONE], [OTP]... tag, i.e. the user typed data that was hidden."""
    return bool(HIDDEN_TAG.search(text or ""))


def search_text(text: str) -> str:
    """The redacted text without its [PHONE], [EMAIL], [OTP]... tags, for the knowledge base search. The tag
    word itself ("phone", "email") would match SOPs about phones and email and pull the search off topic."""
    return re.sub(r"\s{2,}", " ", _TAG.sub("", text)).strip() or text
