from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    provider: str = "ollama"  # "ollama", "openai" or "lmstudio"

    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "qwen3.5:4b"
    ollama_embed_model: str = "nomic-embed-text"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_embed_model: str = "text-embedding-3-small"

    # LM Studio: its local server speaks the OpenAI API. Use the model IDs LM Studio shows
    # (Developer tab, or GET /v1/models). Inside Docker, the host is host.docker.internal.
    lmstudio_base_url: str = "http://host.docker.internal:1234/v1"
    lmstudio_model: str = "qwen3-8b"
    lmstudio_embed_model: str = "text-embedding-nomic-embed-text-v1.5"
    lmstudio_context_window: int = 8192

    # ChromaDB: "http" uses the chroma container, "local" stores files inside the api container
    chroma_mode: str = "http"
    chroma_host: str = "chroma"
    chroma_port: int = 8000
    chroma_local_path: str = "./data/chroma"
    chroma_collection: str = "sops"

    database_url: str = "sqlite:///./data/aihas.db"

    # RAG settings (tuned in Phase 5)
    kb_dir: str = "kb"
    chunk_size: int = 300
    chunk_overlap: int = 50
    top_k: int = 4                      # chunks sent to the LLM
    candidate_k: int = 8                # candidates from each search before fusion
    min_vector_score: float = 0.62      # below this, answer "no procedure found" (tuned with evaluate_retrieval)
    classifier_min_confidence: float = 0.6

    # Automation (Phase 3)
    webhook_url: str = ""               # optional, for example http://localhost:8080/mock/webhook
    max_resets_per_hour: int = 3
    reset_link_minutes: int = 15

    # Sign-in (Phase 5A)
    secret_key: str = ""                # signs login tokens; empty = a random key per start (everyone is signed out on restart)
    token_minutes: int = 60             # how long a login token stays valid
    login_max_failures: int = 5         # wrong passwords per account before a temporary lock
    login_lock_minutes: int = 15        # window for counting failures, and how long the lock lasts
    webhook_secret: str = ""            # if set, /mock/webhook only accepts events that carry it
    frontend_url: str = "http://localhost:8501"   # base of the password reset link in the (mock) email

    # Rate limits (Phase 5B): requests allowed per minute
    chat_per_minute: int = 20           # per signed-in user, on POST /chat
    login_per_minute: int = 20          # per IP address, on POST /auth/login
    reset_per_minute: int = 10          # per IP address, on POST /auth/reset-password

    # Conversation memory and escalation rules (Phase 5C)
    history_turns: int = 3              # earlier question-and-answer pairs given to the model
    history_chars: int = 1500           # hard cap on the history text, to keep the local model fast
    max_unresolved_answers: int = 2     # grounded answers before "it still does not work" goes to a human


settings = Settings()
