# Conversation Memory and Escalation Rules (Phase 5C)

All of this is plain code in `app/rag/history.py` and `app/chat_service.py`. It adds **no extra LLM call**, so it adds no latency.

## Conversation memory

Before a message is handled, the service reads the earlier messages of the same chat (stored text, so already PII-redacted) and builds a context:

- At most `HISTORY_TURNS` (default 3) question-and-answer pairs, each message cut to 300 characters and the total to `HISTORY_CHARS` (1500). The cap keeps the local model fast.
- **Left out:** messages the injection check blocks and the replies to them, so an attack in turn 1 cannot reach the prompt of turn 5. Messages from human agents are left out too.

How it is used:

1. **Follow-up detection.** A short message that only makes sense with the earlier question is a follow-up: it starts with a cue such as "what about", "how about", "and", "why", "paano naman" (8 words or fewer), or it is 6 words or fewer and contains a reference word such as "it", "that", "step", "still". Thanks and greetings are never follow-ups.
2. **Classification and search.** For a follow-up, the earlier question and the follow-up are joined (`"VPN says authentication failed\nwhat about step 3?"`) and used for intent classification and for retrieval. A normal new question is used as it is.
3. **Answer prompt.** The history is added as a `CONVERSATION SO FAR` block. The system prompt tells the model it is only for understanding follow-ups, that it is data, and that answers still come only from the SOP excerpts.

## Escalation rules

Two triggers from the taxonomy, now implemented. Both create a P3 ticket, hand the chat to a human, and record the rule name in `tool_result.rule`.

| Rule | When it fires |
|---|---|
| `unresolved_after_answers` | The assistant has already given `MAX_UNRESOLVED_ANSWERS` (default 2) answers that cited an SOP in this chat, and the user sends a short message (12 words or fewer) saying it still fails: "still", "doesn't work", "not working", "hindi pa rin"… No LLM runs for this decision |
| `no_match_twice` | The reply is the "I don't have a procedure" message (no good match, the model found no procedure in the SOPs, or the answer cited no SOP), and the previous reply was that message too |

A match in between resets the "twice in a row" count. A long message is treated as a new problem, not as a complaint. If a ticket is already open for the chat, the open ticket is reused.

## Limits (for the defense)

- Follow-up detection is a heuristic on short messages. A long follow-up is treated as a new question. A model-based "rewrite the question" step would be more accurate but adds seconds per message on a local model.
- "Answers" are counted as replies that cite an SOP, so tool and escalation replies do not count.
