"""Tests for the fixes made after the 2026-11-24 evaluation run: citations, "no procedure" replies and
intents (see docs/evaluation.md)."""
from types import SimpleNamespace

from sqlalchemy import select

from app.db.models import Ticket
from app.rag.generator import CITE_RE, parse_reply
from app.rag.prompts import (
    CITATION_REMINDER,
    INTENTS,
    NO_ANSWER_MESSAGE,
    OUTPUT_BLOCKED_MESSAGE,
    RAG_SYSTEM_PROMPT,
)
from app.rag.retriever import Chunk, SearchResult
from test_memory import Talk
from test_rag import env, sops  # noqa: F401  (shared fixtures)


class ScriptedLLM:
    """Gives the replies in order, then repeats the last one."""

    def __init__(self, *replies: str):
        self.replies, self.calls = list(replies), []

    def chat(self, messages):
        self.calls.append(messages)
        reply = self.replies[min(len(self.calls), len(self.replies)) - 1]
        return SimpleNamespace(message=SimpleNamespace(content=reply))


def search_with(*chunks: tuple[str, str]) -> SearchResult:
    """chunks: (sop_id, text)."""
    return SearchResult(chunks=[Chunk(f"{s}#0", s, f"Title {s}", t, 0.03, 0.8, 1.0) for s, t in chunks],
                        best_vector_score=0.8)


LOCKED = search_with(("KB-002", "Wait 30 minutes, or reset your password now with KB-001."))


# ---------- citations ----------

def test_the_prompt_has_no_real_sop_id_the_model_could_copy():
    assert not CITE_RE.search(RAG_SYSTEM_PROMPT)
    assert not CITE_RE.search(CITATION_REMINDER)


def test_an_sop_mentioned_inside_a_retrieved_sop_is_not_a_made_up_citation():
    answer = parse_reply("1. Wait 30 minutes [KB-002].\n2. Or reset your password with [KB-001].", LOCKED)
    assert answer.cited_sop_ids == ["KB-002"] and answer.grounded
    assert answer.invalid_citations == [] and answer.referenced_sop_ids == ["KB-001"]
    assert answer.text == "1. Wait 30 minutes [KB-002].\n2. Or reset your password with KB-001."


def test_a_bare_mention_from_the_sop_is_kept_as_written():
    answer = parse_reply("Reset your password with KB-001 [KB-002].", LOCKED)
    assert answer.text == "Reset your password with KB-001 [KB-002]." and not answer.invalid_citations


def test_a_group_of_citations_keeps_only_real_sources():
    answer = parse_reply("Reinstall the client [KB-002, KB-999].", LOCKED)
    assert answer.text == "Reinstall the client [KB-002]."
    assert answer.cited_sop_ids == ["KB-002"] and answer.invalid_citations == ["KB-999"]


def test_a_group_of_real_sources_is_left_as_written():
    search = search_with(("KB-007", "Install it."), ("KB-008", "Fix it."))
    answer = parse_reply("Install and fix it [KB-007, KB-008].", search)
    assert answer.text == "Install and fix it [KB-007, KB-008]." and answer.cited_sop_ids == ["KB-007", "KB-008"]


def test_a_made_up_citation_is_still_removed_and_flagged():
    answer = parse_reply("Wait 30 minutes [KB-002]. See also [KB-999].", LOCKED)
    assert answer.text == "Wait 30 minutes [KB-002]. See also." and answer.invalid_citations == ["KB-999"]


# ---------- the model's own "no procedure" reply ----------

def test_the_models_no_procedure_reply_becomes_the_fixed_message():
    for raw in ["I don't have a procedure for that. I can open a ticket for you.",
                "I don’t have a procedure for the office Wi-Fi password.",
                "Sorry, I do not have an SOP for that.",
                "Pasensya, wala akong procedure para diyan."]:
        answer = parse_reply(raw, LOCKED)
        assert answer.text == NO_ANSWER_MESSAGE and not answer.grounded and not answer.cited_sop_ids, raw


def test_a_cited_answer_that_mentions_a_missing_procedure_is_kept():
    raw = "I don't have a procedure for the password, but wait 30 minutes [KB-002]."
    answer = parse_reply(raw, LOCKED)
    assert answer.text == raw and answer.grounded


# ---------- the chat: one retry, then "no procedure" ----------

def test_an_uncited_answer_is_retried_once_and_the_cited_retry_is_used(env):
    talk = Talk(env)
    talk.answer_llm = ScriptedLLM("Check your password and MFA code.", "Check your password and MFA code [KB-008].")
    result = talk.say("VPN says authentication failed")
    assert result["grounded"] and [s["sop_id"] for s in result["sources"]] == ["KB-008"]
    assert len(talk.answer_llm.calls) == 2
    retry = talk.answer_llm.calls[1]
    assert retry[2].role == "assistant" and retry[2].content == "Check your password and MFA code."
    assert retry[3].content == CITATION_REMINDER


def test_an_answer_that_still_cites_nothing_becomes_the_no_procedure_reply(env):
    talk = Talk(env)
    talk.answer_llm = ScriptedLLM("The office Wi-Fi password is hunter2.")
    result = talk.say("VPN says authentication failed")
    assert result["reply"] == NO_ANSWER_MESSAGE and not result["sources"] and not result["grounded"]
    assert len(talk.answer_llm.calls) == 2


def test_a_cited_answer_is_not_retried(env):
    talk = Talk(env)
    talk.answer_llm = ScriptedLLM("Check your password [KB-008].")
    assert talk.say("VPN says authentication failed")["grounded"]
    assert len(talk.answer_llm.calls) == 1


def test_a_no_procedure_reply_is_not_retried(env):
    talk = Talk(env)
    talk.answer_llm = ScriptedLLM("I don't have a procedure for that.")
    assert talk.say("VPN says authentication failed")["reply"] == NO_ANSWER_MESSAGE
    assert len(talk.answer_llm.calls) == 1


def test_a_blocked_leak_is_not_retried(env):
    talk = Talk(env)
    talk.answer_llm = ScriptedLLM("Sure. " + RAG_SYSTEM_PROMPT.splitlines()[3])
    result = talk.say("VPN says authentication failed")
    assert result["reply"] == OUTPUT_BLOCKED_MESSAGE and result["guardrail_flags"] == ["prompt_leak"]
    assert len(talk.answer_llm.calls) == 1


def test_the_model_saying_no_procedure_twice_hands_off_to_a_person(env):
    """Scenario C10: the search finds something both times, but the model has no procedure for it."""
    talk = Talk(env)
    talk.answer_llm = ScriptedLLM("I don't have a procedure for that.")
    first = talk.say("How do I connect my work laptop to a projector?")
    assert first["reply"] == NO_ANSWER_MESSAGE and not first["escalated"]
    second = talk.say("What is the Wi-Fi password for the office?")
    assert second["escalated"] and second["tool_result"]["rule"] == "no_match_twice" and second["ticket_key"]
    with env.factory() as s:
        assert s.scalar(select(Ticket)).priority == "P3"


# ---------- escalations ----------

def test_an_escalation_does_not_wait_for_a_retry(env):
    talk = Talk(env)
    talk.answer_llm = ScriptedLLM("Disconnect from the network now.")
    result = talk.say("I clicked a link in a strange email")
    assert result["escalated"] and result["reply"].startswith("Disconnect from the network now.")
    assert len(talk.answer_llm.calls) == 1


def test_an_escalation_does_not_start_with_the_ticket_or_person_question(env):
    talk = Talk(env)
    talk.answer_llm = ScriptedLLM("I don't have a procedure for that.")
    result = talk.say("I clicked a link in a strange email")
    assert result["escalated"] and NO_ANSWER_MESSAGE not in result["reply"]
    assert result["reply"].startswith("I am connecting you to a human agent now.")


# ---------- intents ----------

def test_whether_something_is_allowed_goes_to_the_topic_not_to_policy_info():
    policy = INTENTS["policy_info"]["description"]
    assert "or whether something is allowed" not in policy          # the wording that pulled Q21 and Q92 here
    assert "belongs to that topic's intent" in policy
    assert "shared mailboxes" in INTENTS["network_email_help"]["description"]
    assert "network_email_help" in INTENTS["access_request"]["description"]
    assert "accessories" in INTENTS["device_help"]["description"]
