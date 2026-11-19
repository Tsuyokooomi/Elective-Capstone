from app.config import settings


def get_llm(temperature: float = 0.1, json_mode: bool = False):
    """Chat model. Use json_mode=True for the intent classifier."""
    if settings.provider == "openai":
        from llama_index.llms.openai import OpenAI

        extra = {"response_format": {"type": "json_object"}} if json_mode else {}
        return OpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=temperature,
            additional_kwargs=extra,
        )

    from llama_index.llms.ollama import Ollama

    return Ollama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        request_timeout=180.0,
        temperature=temperature,
        json_mode=json_mode,
        context_window=4096,
        # Qwen3 models "think" before they answer, which is slow. Turn that off.
        thinking=False if settings.ollama_model.startswith("qwen3") else None,
    )


def get_embed_model():
    if settings.provider == "openai":
        from llama_index.embeddings.openai import OpenAIEmbedding

        return OpenAIEmbedding(
            model=settings.openai_embed_model, api_key=settings.openai_api_key
        )

    from llama_index.embeddings.ollama import OllamaEmbedding

    nomic = "nomic" in settings.ollama_embed_model
    return OllamaEmbedding(
        model_name=settings.ollama_embed_model,
        base_url=settings.ollama_base_url,
        # nomic-embed-text works best with these task prefixes
        query_instruction="search_query: " if nomic else None,
        text_instruction="search_document: " if nomic else None,
    )
