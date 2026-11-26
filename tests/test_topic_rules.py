"""Fixes after the 2026-11-26 evaluation run: topic rules for the intent, focused retrieval, and a cleaner search text.

The rules are checked against the whole eval set, so they cannot quietly change an intent that is already right."""
import json
from pathlib import Path

import pytest

from app.guardrails.pii import has_redaction_tag, redact_pii, search_text
from app.rag.prompts import INTENTS, RAG_SYSTEM_PROMPT, build_rag_user_prompt, correct_intent, topic_words_match
from app.rag.retriever import Chunk, SearchResult, focus_on_sops
from test_memory import Talk
from test_rag import FakeLLM, env, sops  # noqa: F401  (shared fixtures and fake model)

HERE = Path(__file__).resolve().parent
EVAL_SET = json.loads((HERE / "eval_set.json").read_text(encoding="utf-8"))
SCENARIOS = json.loads((HERE / "eval_conversations.json").read_text(encoding="utf-8"))


def label(intent):
    return f'{{"intent": "{intent}", "confidence": 0.9, "urgent": false}}'


# ---------------------------------------------------------------- the rules themselves

@pytest.mark.parametrize("text, wrong, right", [
    ("Can I use the guest Wi-Fi on my work laptop?", "policy_info", "network_email_help"),            # Q21
    ("What is the Wi-Fi password for the office?", "policy_info", "network_email_help"),             # Q44
    ("What is the mailbox size limit?", "policy_info", "network_email_help"),                        # Q71
    ("How do I create a shared mailbox for my team?", "access_request", "network_email_help"),       # Q91
    ("My OTP is [OTP] but the app says it is invalid.", "out_of_scope", "mfa_setup"),                # C16
    ("My OTP is [OTP] but the app says it is invalid.", "policy_info", "mfa_setup"),
    ("My OTP is [OTP] but the app says it is invalid.", "password_reset", "mfa_setup"),
    ("VPN says authentication failed", "out_of_scope", "vpn_help"),
])
def test_the_failed_labels_are_corrected(text, wrong, right):
    assert correct_intent(text, wrong) == right


@pytest.mark.parametrize("text, intent", [
    ("How quickly are high priority tickets handled for email outages?", "policy_info"),   # a policy question about email
    ("Is the chat assistant available at night?", "policy_info"),
    ("How long must my password be?", "policy_info"),
    ("I need access to the shared mailbox", "access_request"),                             # a request, not a how-to
    ("I need a Confluence account for my team", "access_request"),
    ("I forgot my password and my OTP app is on the old phone", "password_reset"),         # a real password problem
    ("Tell me a joke", "out_of_scope"),
])
def test_other_messages_keep_their_label(text, intent):
    assert correct_intent(text, intent) == intent


def test_the_rules_never_touch_urgent_or_action_labels():
    everything = "My Wi-Fi, VPN, Outlook mailbox, laptop and OTP authenticator code all fail. How do I fix it?"
    for name in ("security_incident", "mfa_lost", "human_request", "hardware_request", "mfa_setup", "vpn_help",
                 "network_email_help", "device_help", "account_locked", "chitchat"):
        assert correct_intent(everything, name) == name
    assert correct_intent(everything, None) is None


def test_the_rules_leave_every_correct_eval_label_alone():
    """With the model right, the rules must change nothing: all 113 questions and every scenario turn that has an intent."""
    checked = 0
    for item in EVAL_SET:
        if item["expected_intent"]:
            text = redact_pii(item["question"])[0]
            assert correct_intent(text, item["expected_intent"]) == item["expected_intent"], item["id"]
            checked += 1
    for scenario in SCENARIOS:
        for turn in scenario["turns"]:
            wanted = (turn.get("expect") or {}).get("intent")
            if wanted:
                assert correct_intent(redact_pii(turn["say"])[0], wanted) == wanted, (scenario["id"], turn["say"])
                checked += 1
    assert checked > 90


def test_the_rules_fix_exactly_the_failed_eval_items():
    """Feed each question the label the model gave in the 2026-11-26 run. Q21, Q44, Q71 and Q91 become right."""
    given = {"Q21": "policy_info", "Q44": "policy_info", "Q71": "policy_info", "Q91": "access_request"}
    for item in EVAL_SET:
        if item["id"] in given:
            assert correct_intent(redact_pii(item["question"])[0], given[item["id"]]) == item["expected_intent"], item["id"]


# ---------------------------------------------------------------- the pipeline uses them

def test_pipeline_corrects_a_wrong_label_and_answers(env):
    talk = Talk(env)
    talk.classifier_llm = FakeLLM(label("policy_info"))
    result = talk.say("What is the mailbox size limit?")
    assert result["intent"] == "network_email_help" and result["route"] == "answer" and result["confidence"] == 1.0


def test_a_how_to_mailbox_question_is_answered_not_turned_into_a_ticket(env):
    talk = Talk(env)
    talk.classifier_llm = FakeLLM(label("access_request"))
    result = talk.say("How do I create a shared mailbox for my team?")
    assert result["route"] == "answer" and result["tool"] is None and not result["pending_confirmation"]


def test_a_real_mailbox_request_is_still_an_action(env):
    talk = Talk(env)
    talk.classifier_llm = FakeLLM(label("access_request"))
    result = talk.say("I need access to the shared mailbox")
    assert result["route"] == "action" and result["intent"] == "access_request"


def test_a_typed_one_time_code_is_answered_not_declined(env):
    talk = Talk(env)
    talk.classifier_llm = FakeLLM(label("out_of_scope"))
    result = talk.say("My OTP is 482913 but the app says it is invalid.")
    assert result["route"] == "answer" and result["intent"] == "mfa_setup" and result["pii_redacted"]
    assert "482913" not in result["reply"]


# ---------------------------------------------------------------- focused retrieval and search text

def chunk(sop_id, rank):
    return Chunk(chunk_id=f"{sop_id}#0", sop_id=sop_id, title=f"Title of {sop_id}", text=f"Text of {sop_id}",
                 score=1 / rank, vector_score=0.8, bm25_score=None)


def test_focus_drops_other_sops_when_the_best_chunk_agrees():
    search = SearchResult(chunks=[chunk("KB-009", 1), chunk("KB-017", 2), chunk("KB-010", 3), chunk("KB-004", 4)],
                          best_vector_score=0.81)
    focused = focus_on_sops(search, ["KB-009", "KB-010"])
    assert [c.sop_id for c in focused.chunks] == ["KB-009", "KB-010"] and focused.best_vector_score == 0.81


def test_focus_changes_nothing_when_the_best_chunk_disagrees_or_nothing_is_found():
    search = SearchResult(chunks=[chunk("KB-017", 1), chunk("KB-009", 2)], best_vector_score=0.7)
    assert focus_on_sops(search, ["KB-009", "KB-010"]) is search
    empty = SearchResult(chunks=[], best_vector_score=0.0)
    assert focus_on_sops(empty, ["KB-009"]) is empty


class FixedRetriever:
    def __init__(self, chunks):
        self.chunks, self.queries = chunks, []

    def search(self, query, *args, **kwargs):
        self.queries.append(query)
        return SearchResult(chunks=self.chunks, best_vector_score=0.8)


def talk_with(env, chunks, intent):
    talk = Talk(env, answer_reply="Check the Wi-Fi settings [KB-009].")
    talk.retriever = FixedRetriever(chunks)
    talk.classifier_llm = FakeLLM(label(intent))
    return talk


def test_the_model_only_sees_the_intents_sops_when_the_search_agrees(env):
    talk = talk_with(env, [chunk("KB-009", 1), chunk("KB-017", 2), chunk("KB-004", 3)], "network_email_help")
    result = talk.say("Hindi gumagana ang Wi-Fi sa opisina")
    prompt = talk.last_answer_prompt()
    assert "[KB-009]" in prompt and "[KB-017]" not in prompt and "[KB-004]" not in prompt
    assert [s["sop_id"] for s in result["sources"]] == ["KB-009"]


def test_the_model_sees_everything_when_the_search_and_the_label_disagree(env):
    talk = talk_with(env, [chunk("KB-017", 1), chunk("KB-009", 2), chunk("KB-004", 3)], "network_email_help")
    talk.say("Hindi gumagana ang Wi-Fi sa opisina")
    prompt = talk.last_answer_prompt()
    assert "[KB-017]" in prompt and "[KB-009]" in prompt and "[KB-004]" in prompt


def test_a_low_confidence_label_does_not_focus_the_search(env):
    talk = talk_with(env, [chunk("KB-009", 1), chunk("KB-017", 2)], "network_email_help")
    talk.classifier_llm = FakeLLM('{"intent": "network_email_help", "confidence": 0.3, "urgent": false}')
    talk.say("something about the office")
    assert "[KB-017]" in talk.last_answer_prompt()


def test_redaction_tags_are_not_searched_for():
    assert search_text("Ang phone ko ay [PHONE]. Hindi gumagana ang Wi-Fi sa opisina.") == \
        "Ang phone ko ay . Hindi gumagana ang Wi-Fi sa opisina."
    assert search_text("My OTP is [OTP] but invalid.") == "My OTP is but invalid."
    assert search_text("[PHONE]") == "[PHONE]"          # nothing else to search with: keep it
    assert search_text("VPN fails") == "VPN fails"


def test_the_search_gets_text_without_the_tags_but_the_stored_message_keeps_them(env):
    talk = talk_with(env, [chunk("KB-009", 1)], "network_email_help")
    talk.say("Ang phone ko ay 0917 123 4567. Hindi gumagana ang Wi-Fi sa opisina.")
    assert "[PHONE]" not in talk.retriever.queries[0] and "0917" not in talk.retriever.queries[0]


# ---------------------------------------------------------------- the prompt

def test_the_prompts_ask_for_citations_and_for_a_refusal_on_a_different_problem():
    assert "related but different problem" in RAG_SYSTEM_PROMPT
    prompt = build_rag_user_prompt("How do I create a shared mailbox?", [{"sop_id": "KB-010", "title": "T", "text": "x"}])
    assert prompt.rstrip().endswith("in front of its excerpt.") and "QUESTION:\nHow do I create a shared mailbox?" in prompt
    assert "KB-" not in prompt.split("QUESTION:")[1]     # no example ID for the model to copy


def test_every_intent_still_has_the_fields_the_pipeline_reads():
    for name, spec in INTENTS.items():
        assert {"description", "route", "tool", "sops", "examples"} <= set(spec), name


# ---------------------------------------------------------------- the soft score bar and the self-contradicting answer

from app.config import settings  # noqa: E402
from app.rag.generator import opens_with_refusal  # noqa: E402
from app.rag.prompts import CONTRADICTION_REMINDER, NO_ANSWER_MESSAGE  # noqa: E402
from test_citations import ScriptedLLM  # noqa: E402


class ScoredRetriever(FixedRetriever):
    def __init__(self, chunks, score):
        super().__init__(chunks)
        self.score = score

    def search(self, query, *args, **kwargs):
        self.queries.append(query)
        return SearchResult(chunks=self.chunks, best_vector_score=self.score)


def scored_talk(env, monkeypatch, chunks, score, intent, confidence=0.9, reply="The limit is 50 GB [KB-010]."):
    monkeypatch.setattr(settings, "min_vector_score", 0.62)
    monkeypatch.setattr(settings, "soft_min_vector_score", 0.45)
    talk = Talk(env, answer_reply=reply)
    talk.retriever = ScoredRetriever(chunks, score)
    talk.classifier_llm = FakeLLM(f'{{"intent": "{intent}", "confidence": {confidence}, "urgent": false}}')
    return talk


def test_a_middling_score_is_answered_when_the_best_chunk_matches_the_intent(env, monkeypatch):      # Q71, Q78
    talk = scored_talk(env, monkeypatch, [chunk("KB-010", 1), chunk("KB-004", 2)], 0.55, "network_email_help")
    result = talk.say("What is the mailbox size limit?")
    assert talk.answer_llm.calls and result["grounded"] and result["sources"][0]["sop_id"] == "KB-010"


def test_a_middling_score_is_still_refused_when_the_best_chunk_is_another_topic(env, monkeypatch):  # Q42, Q43, Q88, Q91, Q92
    talk = scored_talk(env, monkeypatch, [chunk("KB-007", 1), chunk("KB-010", 2)], 0.55, "network_email_help")
    result = talk.say("How do I set up my work email on my personal iPad?")
    assert result["reply"] == NO_ANSWER_MESSAGE and not talk.answer_llm.calls and not result["sources"]


def test_the_soft_bar_has_a_floor_and_needs_a_confident_label(env, monkeypatch):
    low = scored_talk(env, monkeypatch, [chunk("KB-010", 1)], 0.40, "network_email_help")
    assert low.say("What is the mailbox size limit?")["reply"] == NO_ANSWER_MESSAGE and not low.answer_llm.calls
    unsure = scored_talk(env, monkeypatch, [chunk("KB-010", 1)], 0.55, "network_email_help", confidence=0.3)
    assert unsure.say("What is the mailbox size limit?")["reply"] == NO_ANSWER_MESSAGE and not unsure.answer_llm.calls


def test_a_good_score_needs_no_agreement(env, monkeypatch):
    talk = scored_talk(env, monkeypatch, [chunk("KB-007", 1)], 0.70, "network_email_help", reply="Steps [KB-007].")
    assert talk.say("How do I set up the VPN?")["grounded"]


def test_a_rule_set_intent_focuses_the_search_anywhere_in_the_list(env):                            # Q95 / C16
    talk = Talk(env, answer_reply="Check the time on your phone [KB-003].")
    talk.retriever = FixedRetriever([chunk("KB-014", 1), chunk("KB-003", 2), chunk("KB-004", 3)])
    talk.classifier_llm = FakeLLM(label("out_of_scope"))
    result = talk.say("My OTP is 482913 but the app says it is invalid.")
    prompt = talk.last_answer_prompt()
    assert "[KB-003]" in prompt and "[KB-014]" not in prompt and "[KB-004]" not in prompt
    assert result["intent"] == "mfa_setup" and result["sources"][0]["sop_id"] == "KB-003"


def test_focus_anywhere_unit():
    search = SearchResult(chunks=[chunk("KB-014", 1), chunk("KB-003", 2)], best_vector_score=0.7)
    assert [c.sop_id for c in focus_on_sops(search, ["KB-003"], anywhere=True).chunks] == ["KB-003"]
    assert focus_on_sops(search, ["KB-003"]) is search                    # not at rank 1: no change
    assert focus_on_sops(search, ["KB-099"], anywhere=True) is search      # none of them found: no change


def test_opens_with_refusal():
    assert opens_with_refusal("I don't have a procedure for that. The context covers [KB-011].")
    assert opens_with_refusal("Wala po akong procedure para diyan.")
    assert opens_with_refusal("Sorry, I don't have a procedure for that.")
    assert not opens_with_refusal("Restart the laptop. I don't have a procedure for printers.")
    assert not opens_with_refusal("")


def device_talk(env, *replies):
    talk = Talk(env)
    talk.retriever = FixedRetriever([chunk("KB-011", 1)])
    talk.classifier_llm = FakeLLM(label("device_help"))
    talk.answer_llm = ScriptedLLM(*replies)
    return talk


REFUSE_AND_CITE = "I don't have a procedure for that. The context only covers slow computers [KB-011]."


def test_a_refusal_that_still_cites_is_turned_into_the_plain_reply_if_the_model_confirms(env):      # Q90
    talk = device_talk(env, REFUSE_AND_CITE, "I don't have a procedure for that.")
    result = talk.say("How do I reinstall Windows on my laptop?")
    assert result["reply"] == NO_ANSWER_MESSAGE and not result["sources"] and not result["grounded"]
    assert len(talk.answer_llm.calls) == 2 and CONTRADICTION_REMINDER in talk.answer_llm.calls[1][-1].content


def test_a_refusal_that_still_cites_becomes_an_answer_if_the_model_decides_to_answer(env):          # Q96
    talk = device_talk(env, REFUSE_AND_CITE, "1. Restart the laptop. [KB-011]")
    result = talk.say("Call me at 02-8123-4567 about my slow laptop.")
    assert result["grounded"] and result["reply"].startswith("1. Restart") and result["sources"][0]["sop_id"] == "KB-011"


def test_a_model_that_keeps_contradicting_itself_gets_the_plain_reply(env):
    talk = device_talk(env, REFUSE_AND_CITE, REFUSE_AND_CITE)
    result = talk.say("How do I reinstall Windows on my laptop?")
    assert result["reply"] == NO_ANSWER_MESSAGE and not result["sources"] and len(talk.answer_llm.calls) == 2


def test_a_clean_answer_or_a_clean_refusal_costs_no_extra_call(env):
    answered = device_talk(env, "1. Restart the laptop. [KB-011]")
    assert answered.say("My laptop is slow")["grounded"] and len(answered.answer_llm.calls) == 1
    refused = device_talk(env, "I don't have a procedure for that.")
    assert refused.say("How do I reinstall Windows?")["reply"] == NO_ANSWER_MESSAGE and len(refused.answer_llm.calls) == 1


def test_the_answer_prompt_explains_redaction_tags_and_forbids_doing_both():
    assert "[PHONE]" in RAG_SYSTEM_PROMPT and "Never tell the user that you cannot see their data" in RAG_SYSTEM_PROMPT
    assert "Do not do both" in RAG_SYSTEM_PROMPT


# ---------------------------------------------------------------- Q45, Q57, Q95 and C16 of the 2026-11-26 run

def test_topic_words_trust_the_intent_only_when_the_message_names_its_topic():
    assert topic_words_match("Ang bagal ng laptop ko, ano ang pwede kong gawin?", "device_help")      # Q57
    assert topic_words_match("My employee ID is E-1001 and my phone is . The VPN will not connect.", "vpn_help")   # Q45
    assert topic_words_match("My OTP is [OTP] but the app says it is invalid.", "mfa_setup")           # Q95, C16
    assert not topic_words_match("Ang bagal ng laptop ko", "vpn_help")
    assert not topic_words_match("I need a loan laptop", "policy_info") and not topic_words_match("hi", None)


def test_a_slow_laptop_keeps_its_own_sop_even_when_the_loan_sop_ranks_first():
    """Q57: KB-015 (loan laptop) ranked first, so the strict score bar applied and the model was never asked."""
    search = SearchResult(chunks=[chunk("KB-015", 1), chunk("KB-011", 2), chunk("KB-017", 3)], best_vector_score=0.55)
    assert focus_on_sops(search, INTENTS["device_help"]["sops"]) is search            # the plain focus gives up
    focused = focus_on_sops(search, INTENTS["device_help"]["sops"], anywhere=True)    # the trusted focus keeps KB-011
    assert [c.sop_id for c in focused.chunks] == ["KB-011"]


def test_the_prompt_explains_redaction_tags_only_when_there_is_one():
    chunks = [{"sop_id": "KB-003", "title": "T", "text": "x"}]
    tagged = build_rag_user_prompt("My OTP is [OTP] but the app says it is invalid.", chunks)
    plain = build_rag_user_prompt("My code is invalid.", chunks)
    assert "only hide personal data" in tagged and "only hide personal data" not in plain
    assert tagged.rstrip().endswith("in front of its excerpt.") and has_redaction_tag("my phone is [PHONE]")


def test_an_invented_time_is_found_and_a_copied_time_is_not():
    from app.eval.metrics import unsupported_numbers
    sop = "Human helpdesk: Monday to Friday, 8:00 AM to 6:00 PM Philippine Time."
    assert unsupported_numbers("Bukas ito mula 8:00 AM hanggang 5:00 PM [KB-019]", sop) == ["5:00"]
    assert unsupported_numbers("Bukas ito mula 8:00 AM hanggang 6:00 PM [KB-019]", sop) == []
