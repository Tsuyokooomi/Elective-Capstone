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

## Test
```
docker compose exec api python -m pytest tests -q
docker compose exec frontend python -m pytest tests -q
```

## Documentation
- `docs/prompt-taxonomy.md`: intents, routes, and escalation rules
- `docs/database-schema.md`: tables
- `docs/rag-pipeline.md`: indexing, hybrid search, citations
- `docs/function-calling.md`: tools, confirmation, tickets, webhooks
- `docs/ui-and-dashboard.md`: screens, roles, metrics
