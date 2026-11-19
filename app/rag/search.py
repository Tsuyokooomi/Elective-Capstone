"""Try the hybrid search from the command line.

    docker compose exec api python -m app.rag.search "VPN says authentication failed"
"""
import argparse

from app.rag.retriever import HybridRetriever


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("-k", type=int, default=4)
    args = parser.parse_args()

    retriever = HybridRetriever()
    if not retriever.is_ready():
        raise SystemExit("The knowledge base is empty. Run: python -m app.rag.indexer")

    result = retriever.search(args.query, top_k=args.k)
    print(f"Best vector score: {result.best_vector_score:.3f}\n")
    for rank, c in enumerate(result.chunks, start=1):
        vec = "-" if c.vector_score is None else f"{c.vector_score:.3f}"
        bm = "-" if c.bm25_score is None else f"{c.bm25_score:.2f}"
        print(f"{rank}. {c.chunk_id}  {c.title}   fused={c.score:.4f} vector={vec} bm25={bm}")


if __name__ == "__main__":
    main()
