"""Hybrid search: vector search (ChromaDB) plus keyword search (BM25), merged with
reciprocal rank fusion (RRF)."""
from dataclasses import dataclass

from llama_index.retrievers.bm25 import BM25Retriever

from app.config import settings
from app.llm import get_embed_model
from app.rag.chunking import build_nodes, load_sops
from app.rag.store import get_collection

RRF_K = 60


@dataclass
class Chunk:
    chunk_id: str
    sop_id: str
    title: str
    text: str
    score: float                    # fused (RRF) score, used for ranking
    vector_score: float | None      # cosine similarity, None if only BM25 found it
    bm25_score: float | None


@dataclass
class SearchResult:
    chunks: list[Chunk]
    best_vector_score: float        # best cosine similarity among all vector candidates


def fuse(vector_hits: list[dict], bm25_hits: list[dict], top_k: int) -> list[Chunk]:
    """Reciprocal rank fusion. Each hit is a dict with chunk_id, sop_id, title, text, score."""
    merged: dict[str, Chunk] = {}
    for hits, field in ((vector_hits, "vector_score"), (bm25_hits, "bm25_score")):
        for rank, hit in enumerate(hits, start=1):
            chunk = merged.get(hit["chunk_id"])
            if chunk is None:
                chunk = Chunk(
                    chunk_id=hit["chunk_id"], sop_id=hit["sop_id"], title=hit["title"],
                    text=hit["text"], score=0.0, vector_score=None, bm25_score=None,
                )
                merged[hit["chunk_id"]] = chunk
            chunk.score += 1.0 / (RRF_K + rank)
            setattr(chunk, field, hit["score"])
    return sorted(merged.values(), key=lambda c: c.score, reverse=True)[:top_k]


class HybridRetriever:
    def __init__(self, embed_model=None, collection=None, sops=None):
        self.embed_model = embed_model or get_embed_model()
        self.collection = collection if collection is not None else get_collection()
        self.reload(sops)

    def reload(self, sops=None) -> None:
        """Rebuild the in-memory BM25 index from the KB files."""
        nodes = build_nodes(sops if sops is not None else load_sops())
        self.nodes_by_id = {n.id_: n for n in nodes}
        self.bm25 = (
            BM25Retriever.from_defaults(
                nodes=nodes, similarity_top_k=min(settings.candidate_k, len(nodes))
            )
            if nodes else None
        )

    def is_ready(self) -> bool:
        return self.collection.count() > 0 and self.bm25 is not None

    def vector_search(self, query: str, k: int) -> list[dict]:
        total = self.collection.count()
        if total == 0:
            return []
        embedding = self.embed_model.get_query_embedding(query)
        result = self.collection.query(
            query_embeddings=[embedding],
            n_results=min(k, total),
            include=["documents", "metadatas", "distances"],
        )
        hits = []
        for doc, meta, dist in zip(result["documents"][0], result["metadatas"][0], result["distances"][0]):
            hits.append({
                "chunk_id": meta["chunk_id"], "sop_id": meta["sop_id"], "title": meta["title"],
                "text": doc, "score": 1.0 - float(dist),
            })
        return hits

    def bm25_search(self, query: str) -> list[dict]:
        if self.bm25 is None:
            return []
        hits = []
        for item in self.bm25.retrieve(query):
            if item.score is None or item.score <= 0:
                continue
            node = item.node
            hits.append({
                "chunk_id": node.id_, "sop_id": node.metadata["sop_id"],
                "title": node.metadata["title"], "text": node.get_content(),
                "score": float(item.score),
            })
        return hits

    def search(self, query: str, top_k: int | None = None) -> SearchResult:
        vector_hits = self.vector_search(query, settings.candidate_k)
        bm25_hits = self.bm25_search(query)
        best = max((h["score"] for h in vector_hits), default=0.0)
        chunks = fuse(vector_hits, bm25_hits, top_k or settings.top_k)
        return SearchResult(chunks=chunks, best_vector_score=best)
