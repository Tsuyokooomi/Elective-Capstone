import chromadb

from app.config import settings


def get_client():
    if settings.chroma_mode == "local":
        return chromadb.PersistentClient(path=settings.chroma_local_path)
    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)


def get_collection(client=None, name: str | None = None):
    client = client or get_client()
    return client.get_or_create_collection(
        name=name or settings.chroma_collection,
        metadata={"hnsw:space": "cosine"},  # scores become cosine similarity (1 = identical)
    )
