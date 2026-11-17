# Elective Capstone

AI-powered enterprise helpdesk and workflow automation system (AI-HAS).
Stack: FastAPI, ChromaDB, OpenAI gpt-4o-mini, LangChain, Streamlit.

## Run
1. Copy `.env.example` to `.env` and add your OpenAI key.
2. `docker compose up --build`
3. Open http://localhost:8080/health

## Test
`pip install -r requirements.txt` then `pytest`
