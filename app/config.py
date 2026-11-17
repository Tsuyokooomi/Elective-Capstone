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

    chroma_host: str = "chroma"
    chroma_port: int = 8000
    database_url: str = "sqlite:///./data/aihas.db"


settings = Settings()