"""Conversation memory and the rule-based escalation checks (Phase 5C).

The chat service reads the stored messages of the conversation and builds a Context from them.
Everything here is plain code (no LLM call), so it adds no latency and is easy to test.

What goes into the history:
- Only stored text, which is already PII-redacted.
- Not the messages that the injection check blocks, and not the replies to them, so an attack in
  turn 1 cannot reach the prompt of turn 5.
- Not messages written by human agents.
- At most HISTORY_TURNS question-and-answer pairs, cut to HISTORY_CHARS, so the local model stays fast."""
import re
from dataclasses import dataclass, field

from app.config import settings
from app.guardrails.injection import looks_like_injection
from app.rag.prompts import INJECTION_BLOCKED_MESSAGE

THANKS_OR_GREETING = re.compile(
    r"\b(thanks|thank you|salamat|hello|hi|hey|kumusta|good (?:morning|afternoon|evening))\b", re.I)
FOLLOW_UP_START = re.compile(
    r"^\W*(?:and|but|so|then|also|what about|how about|why|what if|okay but|ok but|how come|paano naman|"
    r"e paano|tapos|ano naman|eh|yung|iyon|iyan)\b", re.I)
REFERENCE_WORDS = {
    "it", "that", "this", "those", "these", "them", "there", "again", "same", "step", "steps", "still", "also",
    "too", "one", "yun", "yan", "iyon", "iyan", "ito", "niyan",
}
UNRESOLVED = re.compile(
    r"\b(?:still|didn'?t work|doesn'?t work|did not work|does not work|not working|no luck|"
    r"same (?:error|problem|issue|thing)|hindi (?:pa rin|gumana|umubra|ito gumana)|wala pa rin|ayaw pa rin|di pa rin)\b",
    re.I)

TURN_CHARS = 300   # each earlier message is cut to this length


@dataclass
class Context:
    turns: list[dict] = field(default_factory=list)   # [{"role": "user" | "assistant", "text": ...}], oldest first
    last_user: str | None = None          # the previous real question from the user
    last_assistant: str | None = None     # the previous reply from the assistant
    grounded_answers: int = 0             # answers in this chat that cited at least one SOP


def _words(text: str) -> list[str]:
    return re.findall(r"[\w'’-]+", text.lower())


def is_follow_up(text: str) -> bool:
    """A short message that only makes sense with the earlier question: "what about step 3?"."""
    if THANKS_OR_GREETING.search(text):
        return False
    words = _words(text)
    if not words:
        return False
    if FOLLOW_UP_START.match(text):
        return len(words) <= 8
    return len(words) <= 6 and any(w in REFERENCE_WORDS for w in words)


def unresolved_complaint(text: str) -> bool:
    """A short "it still does not work" message. Long messages are probably a new problem."""
    return bool(UNRESOLVED.search(text)) and len(_words(text)) <= 12


def build_context(rows: list[tuple[str, str]], grounded_answers: int = 0) -> Context:
    """rows: (sender, content) for the earlier messages of the chat, oldest first."""
    turns: list[dict] = []
    skip_reply = False
    for sender, content in rows:
        if sender == "user":
            if looks_like_injection(content):
                skip_reply = True
                continue
            skip_reply = False
            turns.append({"role": "user", "text": content})
        elif sender == "assistant":
            if skip_reply or content == INJECTION_BLOCKED_MESSAGE:
                skip_reply = False
                continue
            turns.append({"role": "assistant", "text": content})
        # messages from human agents are left out

    turns = turns[-(settings.history_turns * 2):]
    turns = [{"role": t["role"], "text": t["text"][:TURN_CHARS]} for t in turns]
    while len(turns) > 1 and sum(len(t["text"]) for t in turns) > settings.history_chars:
        turns.pop(0)

    last_user = next((t["text"] for t in reversed(turns)
                      if t["role"] == "user" and len(_words(t["text"])) >= 3
                      and not THANKS_OR_GREETING.search(t["text"])), None)
    last_assistant = next((t["text"] for t in reversed(turns) if t["role"] == "assistant"), None)
    return Context(turns=turns, last_user=last_user, last_assistant=last_assistant,
                   grounded_answers=grounded_answers)


def contextual_question(text: str, ctx: Context) -> str | None:
    """For a follow-up, the earlier question plus the follow-up, used for classification and search."""
    if ctx.last_user and is_follow_up(text):
        return f"{ctx.last_user}\n{text}"
    return None
