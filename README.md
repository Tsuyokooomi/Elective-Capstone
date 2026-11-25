# Elective Capstone

AI-powered enterprise helpdesk and workflow automation system (AI-HAS) for the fictional CapstoneCompany.

Stack: FastAPI, ChromaDB, LlamaIndex, Ollama (OpenAI optional), SQLite, Streamlit, Docker.

## Run
1. Install Ollama, then run `ollama pull qwen3.5:4b` and `ollama pull nomic-embed-text`.
2. Copy `.env.example` to `.env`.
3. Start Docker Desktop, then run `docker compose up --build`.
4. In a second terminal, run:
   - `docker compose exec api python -m app.db.seed` (demo users and SOP records)
   - `docker compose exec api python -m app.rag.indexer` (index the SOPs)
5. Open the chat interface at http://localhost:8501 and the API docs at http://localhost:8080/docs.

### Using LM Studio instead of Ollama
1. In LM Studio, download a chat model (for example Qwen3 8B) and an embedding model (for example nomic-embed-text v1.5).
2. Open the Developer tab, load both models, and start the server (port 1234).
3. In `.env`, set `PROVIDER=lmstudio` and set `LMSTUDIO_MODEL` and `LMSTUDIO_EMBED_MODEL` to the model IDs LM Studio shows.
4. Follow steps 3 to 5 above. Re-run the indexer whenever you change the embedding model.

## Test
```
docker compose exec api python -m pytest tests -q
docker compose exec frontend python -m pytest tests -q
```
The same tests run on every push through GitHub Actions (`.github/workflows/ci.yml`). See `docs/testing-and-ci.md`.

## Evaluate
```
docker compose exec api python -m app.eval.run_eval                     # full evaluation (several minutes)
docker compose exec api python -m app.eval.run_eval --suite guardrails  # red-team check, seconds
docker compose exec api python -m app.eval.load_test                    # stress test of the running API
```
Reports are written to `data/eval/`. See `docs/evaluation.md`.

## Documentation
- `docs/prompt-taxonomy.md`: intents, routes, and escalation rules
- `docs/database-schema.md`: tables
- `docs/rag-pipeline.md`: indexing, hybrid search, citations
- `docs/function-calling.md`: tools, confirmation, tickets, webhooks
- `docs/ui-and-dashboard.md`: screens, roles, metrics
- `docs/authentication.md`: login tokens, roles, password reset link, lockout
- `docs/guardrails.md`: rate limits, PII redaction, injection check, output filter
- `docs/memory-and-escalation.md`: conversation memory and the two escalation rules
- `docs/evaluation.md`: how the assistant is scored, and how to run the evaluation and the load test
- `docs/testing-and-ci.md`: the test suites and the CI pipeline
