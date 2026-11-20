import re
from dataclasses import dataclass, field

from llama_index.core.llms import ChatMessage

from app.config import settings
from app.rag.prompts import NO_ANSWER_MESSAGE, RAG_SYSTEM_PROMPT, build_rag_user_prompt
from app.rag.retriever import SearchResult

CITE_RE = re.compile(r"KB-\d{3}")
THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


@dataclass
class Answer:
    text: str
    cited_sop_ids: list[str] = field(default_factory=list)   # valid citations only
    invalid_citations: list[str] = field(default_factory=list)  # SOP ids the model made up
    grounded: bool = False       # True if the answer cites at least one retrieved SOP
    used_llm: bool = False


def generate_answer(question: str, search: SearchResult, llm, min_score: float | None = None) -> Answer:
    min_score = settings.min_vector_score if min_score is None else min_score

    # No good match: do not ask the LLM, so it has nothing to invent from.
    if not search.chunks or search.best_vector_score < min_score:
        return Answer(text=NO_ANSWER_MESSAGE)

    chunks = [{"sop_id": c.sop_id, "title": c.title, "text": c.text} for c in search.chunks]
    response = llm.chat(
        [
            ChatMessage(role="system", content=RAG_SYSTEM_PROMPT),
            ChatMessage(role="user", content=build_rag_user_prompt(question, chunks)),
        ]
    )
    text = THINK_RE.sub("", response.message.content or "").strip()

    allowed = {c.sop_id for c in search.chunks}
    found = list(dict.fromkeys(CITE_RE.findall(text)))
    cited = [s for s in found if s in allowed]
    invalid = [s for s in found if s not in allowed]
    for sop_id in invalid:   # a citation the user cannot trace must not stay in the reply
        text = re.sub(rf"\s*\[{sop_id}\]", "", text)
    return Answer(text=text, cited_sop_ids=cited, invalid_citations=invalid,
                  grounded=bool(cited), used_llm=True)
