import re
from dataclasses import dataclass, field

from llama_index.core.llms import ChatMessage

from app.config import settings
from app.rag.prompts import CITATION_REMINDER, NO_ANSWER_MESSAGE, RAG_SYSTEM_PROMPT, build_rag_user_prompt
from app.rag.retriever import SearchResult

CITE_RE = re.compile(r"KB-\d{3}")
BRACKET_RE = re.compile(r"([ \t]*)\[([^\[\]\n]*?KB-\d{3}[^\[\]\n]*?)\]")   # [KB-001] or [KB-007, KB-008]
THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
# The model's own "no procedure" reply (rule 3 of the prompt), in English or Filipino
REFUSAL_RE = re.compile(
    r"\b(?:don[’']?t|do not|doesn[’']?t|does not) have (?:a |an |any )?(?:procedure|sop)\b"
    r"|\bno (?:procedure|sop) (?:for|on|about)\b"
    r"|\bwala(?:ng| akong| kaming| po akong) (?:procedure|proseso|sop)\b",
    re.IGNORECASE,
)


@dataclass
class Answer:
    text: str
    cited_sop_ids: list[str] = field(default_factory=list)   # valid citations only
    invalid_citations: list[str] = field(default_factory=list)  # SOP ids the model made up
    referenced_sop_ids: list[str] = field(default_factory=list)  # ids a retrieved SOP itself mentions ("see KB-002")
    grounded: bool = False       # True if the answer cites at least one retrieved SOP
    used_llm: bool = False


def parse_reply(raw: str, search: SearchResult) -> Answer:
    """Turn the model's text into an Answer and sort the SOP ids it contains.

    - cited: ids of retrieved SOPs. Only these are shown to the user as sources.
    - referenced: ids that are not retrieved but appear inside a retrieved SOP ("see KB-002").
      The model only repeated the SOP, so this is not a made-up citation. A bracket around such an id
      is removed (it is not a source we can show), the id itself stays as plain text.
    - invalid: ids found nowhere in the CONTEXT. A bracketed one is removed from the reply."""
    original = THINK_RE.sub("", raw or "").strip()
    allowed = {c.sop_id for c in search.chunks}
    in_context = {s for c in search.chunks for s in CITE_RE.findall(c.text)} - allowed

    def rewrite(match: re.Match) -> str:
        lead, ids = match.group(1), list(dict.fromkeys(CITE_RE.findall(match.group(2))))
        keep = [s for s in ids if s in allowed]
        if len(keep) == len(ids):
            return match.group(0)                       # every id is a real source: leave it as written
        if keep:
            return lead + "[" + ", ".join(keep) + "]"
        mentioned = [s for s in ids if s in in_context]
        return lead + ", ".join(mentioned) if mentioned else ""   # made-up only: drop it with its space

    text = BRACKET_RE.sub(rewrite, original)
    found = list(dict.fromkeys(CITE_RE.findall(original)))
    cited = [s for s in found if s in allowed]
    referenced = [s for s in found if s in in_context]
    invalid = [s for s in found if s not in allowed and s not in in_context]

    if not cited and REFUSAL_RE.search(text):
        # The model said it has no procedure. Use our fixed reply, so the user always gets the same
        # offer (ticket or person) and the "no procedure found twice" rule can count it.
        return Answer(text=NO_ANSWER_MESSAGE, used_llm=True)
    return Answer(text=text, cited_sop_ids=cited, invalid_citations=invalid, referenced_sop_ids=referenced,
                  grounded=bool(cited), used_llm=True)


def generate_answer(question: str, search: SearchResult, llm, min_score: float | None = None,
                    history: list[dict] | None = None, previous: str | None = None) -> Answer:
    """previous: an earlier reply to the same question that cited no SOP. The model sees it and is
    asked once to fix it (see CITATION_REMINDER)."""
    min_score = settings.min_vector_score if min_score is None else min_score

    # No good match: do not ask the LLM, so it has nothing to invent from.
    if not search.chunks or search.best_vector_score < min_score:
        return Answer(text=NO_ANSWER_MESSAGE)

    chunks = [{"sop_id": c.sop_id, "title": c.title, "text": c.text} for c in search.chunks]
    messages = [
        ChatMessage(role="system", content=RAG_SYSTEM_PROMPT),
        ChatMessage(role="user", content=build_rag_user_prompt(question, chunks, history)),
    ]
    if previous is not None:
        messages += [ChatMessage(role="assistant", content=previous),
                     ChatMessage(role="user", content=CITATION_REMINDER)]
    response = llm.chat(messages)
    return parse_reply(response.message.content or "", search)
