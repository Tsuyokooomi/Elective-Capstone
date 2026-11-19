import hashlib
from pathlib import Path

from llama_index.core import Document
from llama_index.core.node_parser import SentenceSplitter

from app.config import settings


def read_field(text: str, label: str) -> str:
    for line in text.splitlines():
        if line.startswith(f"{label}:"):
            return line.split(":", 1)[1].strip()
    return ""


def load_sops(kb_dir: str | None = None) -> list[dict]:
    """Read every KB-*.md file and return one dict per SOP."""
    sops = []
    for path in sorted(Path(kb_dir or settings.kb_dir).glob("KB-*.md")):
        text = path.read_text(encoding="utf-8")
        sop_id = read_field(text, "SOP ID")
        if not sop_id:
            continue
        sops.append(
            {
                "sop_id": sop_id,
                "title": text.splitlines()[0].lstrip("# ").strip(),
                "category": read_field(text, "Category"),
                "checksum": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "text": text,
            }
        )
    return sops


def build_nodes(sops: list[dict], chunk_size: int | None = None, chunk_overlap: int | None = None):
    """Split SOPs into chunks. Chunk ids look like KB-001#0, KB-001#1."""
    splitter = SentenceSplitter(
        chunk_size=chunk_size or settings.chunk_size,
        chunk_overlap=chunk_overlap if chunk_overlap is not None else settings.chunk_overlap,
    )
    nodes = []
    for sop in sops:
        doc = Document(
            text=sop["text"],
            metadata={"sop_id": sop["sop_id"], "title": sop["title"], "category": sop["category"]},
            excluded_embed_metadata_keys=["category"],
            excluded_llm_metadata_keys=["category"],
        )
        for i, node in enumerate(splitter.get_nodes_from_documents([doc])):
            node.id_ = f"{sop['sop_id']}#{i}"
            node.relationships = {}
            nodes.append(node)
    return nodes
