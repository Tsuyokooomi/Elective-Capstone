"""Chunk the SOPs, embed them, and store them in ChromaDB.

Run from the project root:
    python -m app.rag.indexer            # index new or changed SOPs only
    python -m app.rag.indexer --force    # rebuild everything
In Docker:
    docker compose exec api python -m app.rag.indexer
"""
import argparse

from llama_index.core.schema import MetadataMode
from sqlalchemy import select

from app.db.models import KBDocument, utcnow
from app.db.session import SessionLocal, init_db
from app.llm import get_embed_model
from app.rag.chunking import build_nodes, load_sops
from app.rag.store import get_collection


def index_sops(force=False, embed_model=None, collection=None, sops=None, session_factory=None) -> dict:
    session_factory = session_factory or SessionLocal
    sops = sops if sops is not None else load_sops()
    embed_model = embed_model or get_embed_model()
    collection = collection if collection is not None else get_collection()

    summary = {"indexed": 0, "skipped": 0, "chunks": 0, "removed": 0}

    # Remove chunks of SOP files that no longer exist
    current_ids = {s["sop_id"] for s in sops}
    stored = collection.get(include=["metadatas"])
    stale = sorted({m["sop_id"] for m in stored["metadatas"] if m["sop_id"] not in current_ids})
    for sop_id in stale:
        collection.delete(where={"sop_id": sop_id})
        summary["removed"] += 1

    with session_factory() as session:
        for sop in sops:
            # Read only. No database lock is held while we embed and write to ChromaDB.
            doc = session.scalar(select(KBDocument).where(KBDocument.sop_id == sop["sop_id"]))
            in_store = bool(collection.get(where={"sop_id": sop["sop_id"]})["ids"])
            unchanged = (
                doc is not None and doc.indexed_at is not None
                and doc.checksum == sop["checksum"] and in_store
            )
            if unchanged and not force:
                summary["skipped"] += 1
                continue

            nodes = build_nodes([sop])
            texts = [n.get_content(metadata_mode=MetadataMode.EMBED) for n in nodes]
            embeddings = embed_model.get_text_embedding_batch(texts)

            collection.delete(where={"sop_id": sop["sop_id"]})
            collection.add(
                ids=[n.id_ for n in nodes],
                embeddings=embeddings,
                documents=[n.get_content() for n in nodes],
                metadatas=[
                    {"sop_id": sop["sop_id"], "title": sop["title"],
                     "category": sop["category"], "chunk_id": n.id_}
                    for n in nodes
                ],
            )

            # Short write transaction: update the row and commit at once.
            if doc is None:
                doc = KBDocument(sop_id=sop["sop_id"], title=sop["title"],
                                 category=sop["category"], checksum=sop["checksum"])
                session.add(doc)
            doc.title, doc.category, doc.checksum = sop["title"], sop["category"], sop["checksum"]
            doc.indexed_at = utcnow()
            session.commit()
            summary["indexed"] += 1
            summary["chunks"] += len(nodes)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Index the SOP files into ChromaDB")
    parser.add_argument("--force", action="store_true", help="re-index every SOP")
    args = parser.parse_args()

    init_db()
    try:
        result = index_sops(force=args.force)
    except Exception as exc:  # connection problems are the usual cause
        raise SystemExit(
            f"Indexing failed: {type(exc).__name__}: {exc}\n"
            "Check that Ollama is running, the embedding model is pulled, and ChromaDB is up."
        )
    print(
        f"Indexed {result['indexed']} SOPs ({result['chunks']} chunks), "
        f"skipped {result['skipped']}, removed {result['removed']}."
    )


if __name__ == "__main__":
    main()
