"""Phase 5F tests: the fixes made after the first full evaluation run."""
import json
from pathlib import Path

from app.config import settings
from app.rag.prompts import CLASSIFIER_SYSTEM_PROMPT_HEAD, INTENTS, build_classifier_prompt
from test_memory import Talk
from test_rag import FakeLLM, env, sops  # noqa: F401  (shared fixtures and fake model)

OUT_OF_SCOPE = '{"intent": "out_of_scope", "confidence": 0.9, "urgent": false}'
EVAL_SET = json.loads((Path(__file__).resolve().parent / "eval_set.json").read_text(encoding="utf-8"))


def test_the_classifier_is_told_not_to_use_out_of_scope_for_it_questions():
    assert 'if no intent fits' not in CLASSIFIER_SYSTEM_PROMPT_HEAD          # the rule that caused the first-run misses
    assert "closest IT intent" in CLASSIFIER_SYSTEM_PROMPT_HEAD
    assert "company IT" in INTENTS["out_of_scope"]["description"]
    assert "out_of_scope" in build_classifier_prompt()


def _plain(text: str) -> str:
    return text.strip().lower().rstrip("?.! ")


def test_prompt_examples_are_not_copied_from_the_eval_set():
    """Examples in the prompt must not be eval questions (or the start of one), or the evaluation would
    partly test memorised answers."""
    questions = [_plain(q["question"]) for q in EVAL_SET]
    for name, spec in INTENTS.items():
        for example in spec["examples"]:
            e = _plain(example)
            for q in questions:
                assert not (q == e or q.startswith(e) or e.startswith(q)), (name, example, q)


def test_a_strong_sop_match_overrides_a_wrong_out_of_scope_label(env):
    talk = Talk(env)
    talk.classifier_llm = FakeLLM(OUT_OF_SCOPE)
    result = talk.say("VPN says authentication failed")          # the test search always finds KB-008 (min score is 0)
    assert result["route"] == "answer" and result["intent"] is None
    assert result["grounded"] and talk.answer_llm.calls


def test_a_real_out_of_scope_question_is_still_declined(env, monkeypatch):
    monkeypatch.setattr(settings, "min_vector_score", 2.0)       # nothing in the knowledge base matches
    talk = Talk(env)
    talk.classifier_llm = FakeLLM(OUT_OF_SCOPE)
    result = talk.say("What is the capital of France?")
    assert result["route"] == "decline" and not talk.answer_llm.calls


def test_a_malformed_classifier_reply_still_gets_an_answer_when_the_sop_matches(env):
    talk = Talk(env)
    talk.classifier_llm = FakeLLM("this is not json")            # parse_intent falls back to out_of_scope
    result = talk.say("VPN says authentication failed")
    assert result["route"] == "answer" and result["grounded"]
