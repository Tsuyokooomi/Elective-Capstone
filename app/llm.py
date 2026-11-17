from app.config import settings


def get_llm():
    if settings.provider == "openai":
        from llama_index.llms.openai import OpenAI

        return OpenAI(model=settings.openai_model, api_key=settings.openai_api_key)

    from llama_index.llms.ollama import Ollama

    return Ollama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        request_timeout=120.0,
    )


def get_embed_model():
    if settings.provider == "openai":
        from llama_index.embeddings.openai import OpenAIEmbedding

        return OpenAIEmbedding(
            model=settings.openai_embed_model, api_key=settings.openai_api_key
        )

    from llama_index.embeddings.ollama import OllamaEmbedding

    return OllamaEmbedding(
        model_name=settings.ollama_embed_model,
        base_url=settings.ollama_base_url,
    )