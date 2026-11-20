from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    provider: str = "ollama"  # "ollama" or "openai"

    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "qwen3.5:4b"
    ollama_embed_model: str = "nomic-embed-text"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_embed_model: str = "text-embedding-3-small"

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
    min_vector_score: float = 0.35      # below this, answer "no procedure found"
    classifier_min_confidence: float = 0.6

    # Automation (Phase 3)
    webhook_url: str = ""               # optional, for example http://localhost:8080/mock/webhook
    max_resets_per_hour: int = 3
    reset_link_minutes: int = 15


settings = Settings()
