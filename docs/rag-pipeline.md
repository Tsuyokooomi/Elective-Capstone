# RAG Pipeline

## Flow of one chat message

1. **Redact PII.** Emails, Philippine mobile numbers, and card-like numbers become tags such as `[PHONE]`. Only the redacted text is stored and sent to the LLM.
2. **Injection check.** Messages that try to override the rules are blocked before any LLM call.
3. **Security pattern check.** Phishing, malware, and lost-device phrases set the intent to `security_incident` at once.
4. **Intent classification.** The LLM returns JSON (intent, confidence, urgent). If the model is unsure it says "out of scope" with low confidence, and the system lets retrieval decide.
5. **Routing.** Each intent maps to a route (answer, action, escalate, decline). See `prompt-taxonomy.md`.
6. **Retrieval and answer.** For answer, action, and some escalate routes, the system runs hybrid search and asks the LLM to answer from the retrieved SOP text.
7. **Citation check.** The reply keeps only citations that match retrieved SOPs, and only those are shown as sources. An SOP ID that a retrieved SOP itself mentions ("see KB-002") is a reference, not a made-up citation: its brackets are removed and the ID stays as plain text. Any other SOP ID is made up: it is removed and counted in `invalid_citations`.
   - If the model says it has no procedure and cites nothing, the reply becomes the fixed "no procedure" message, so the `no_match_twice` rule can count it.
   - If the answer cites no SOP at all, the model is asked once more to cite its sources (`CITATION_REMINDER`). If the second answer still cites nothing, the user gets the "no procedure" message, because nobody could check where the answer came from. Escalations skip the retry, so a person is reached without waiting.
8. **Logging.** The message, intent, latency, and cited sources go to the database.

## Indexing

- `app/rag/chunking.py` reads every `kb/KB-*.md` file and splits it with LlamaIndex `SentenceSplitter` (300 tokens, 50 overlap). Chunk IDs look like `KB-001#0`.
- `app/rag/indexer.py` embeds each chunk with `nomic-embed-text` and stores it in ChromaDB (cosine distance).
- A checksum in `kb_documents` shows which SOPs changed, so only those are re-indexed. Deleted SOP files are removed from the index.

## Hybrid search

- **Vector search** in ChromaDB finds chunks with similar meaning. Score: cosine similarity from 0 to 1.
- **Keyword search** (BM25) finds chunks that share exact words, such as "VPN" or "Outlook".
- **Reciprocal rank fusion** merges both rankings: each chunk scores the sum of `1 / (60 + rank)` over the two lists. A chunk that ranks well in both lists comes first.

## "No answer" rule

If the best vector score is below `MIN_VECTOR_SCORE`, the system skips the LLM and replies that no procedure was found. The LLM then has nothing to invent from. Tune the value with `python -m app.rag.evaluate_retrieval`.

Above the threshold, the same message is used when the model says it has no procedure, or gives an answer that cites no SOP even after one retry (see step 7).

## Endpoints

| Method and path | Purpose |
|---|---|
| POST `/chat` | Send a message and get a grounded reply with sources |
| GET `/kb` | List the indexed SOPs |
| GET `/kb/search?q=...&k=4` | Debug view of the hybrid search results and scores |
| GET `/health` | Health check |

## Commands

```
docker compose exec api python -m app.rag.indexer            # index new or changed SOPs
docker compose exec api python -m app.rag.indexer --force    # rebuild everything
docker compose exec api python -m app.rag.search "question"  # try the search
docker compose exec api python -m app.rag.evaluate_retrieval # score retrieval, suggest a threshold
docker compose exec api python -m pytest tests -q            # run all tests
docker compose exec api python -m app.eval.run_eval          # score the whole pipeline (see evaluation.md)
```

## Settings (in `app/config.py`, override in `.env`)

| Setting | Default | Meaning |
|---|---|---|
| CHUNK_SIZE | 300 | Tokens per chunk |
| CHUNK_OVERLAP | 50 | Tokens shared by neighbouring chunks |
| TOP_K | 4 | Chunks sent to the LLM |
| CANDIDATE_K | 8 | Candidates taken from each search before fusion |
| MIN_VECTOR_SCORE | 0.62 | Below this, answer "no procedure found". Tuned on the 35 answerable and no-answer questions of the first eval set (answerable scores started at 0.67, no-answer scores went up to 0.74, so no value separates them perfectly). Re-check it with `evaluate_retrieval` and `run_eval` after changing the SOPs or the embedding model |
| SOFT_MIN_VECTOR_SCORE | 0.45 | A lower bar used only when the classifier is confident and the best-ranked chunk belongs to the intent's own SOPs (`INTENTS[...]["sops"]`). It rescues questions such as "What is the mailbox size limit?" whose score is middling although the right SOP ranks first. Questions whose best chunk is another SOP still need `MIN_VECTOR_SCORE`. Chosen from the 2026-11-26 run without the real scores: check it with `evaluate_retrieval` |
| CLASSIFIER_MIN_CONFIDENCE | 0.6 | Below this, an "out of scope" result is ignored |
