# Elective Capstone

AI-powered enterprise helpdesk and workflow automation system (AI-HAS).
Stack: FastAPI, ChromaDB, LlamaIndex, Ollama (OpenAI optional), Streamlit.

## Run
1. Install Ollama, then run `ollama pull qwen3.5:4b` and `ollama pull nomic-embed-text`.
2. Copy `.env.example` to `.env`.
3. Start Docker Desktop, then run `docker compose up --build`.
4. Open http://localhost:8080/health

## Test
`pip install -r requirements.txt` then `pytest`