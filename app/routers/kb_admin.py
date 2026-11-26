"""Admin tools for the knowledge base: add a new SOP and edit an existing one.

POST /kb           builds a new KB-xxx-title.md file from a form (title, category, body) and gives it the next free ID.
PUT  /kb/{sop_id}  replaces the text of an existing SOP. The SOP ID line must stay the same.
DELETE /kb/{sop_id} moves the file to kb/.deleted/ (so it can be restored by moving it back) and removes its chunks
                    from the search index. The database row stays, because past chats cite it, but /kb stops listing it.
GET  /kb/{sop_id}/references lists the other SOPs that mention this one, so the admin sees what a delete leaves dangling.
Add and edit write the file in the kb folder, then index it right away so the assistant can cite it in the next chat.
If indexing fails (for example Ollama is not running), the file is still saved and the reply says so,
so the admin can run Re-index later.

Text that looks like a password, one-time code, card number or government ID is refused: an SOP is read by every
employee and sent to the language model. Company emails and phone numbers are fine, because SOPs name them."""
import logging
import os
import re
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.db.models import User
from app.db.session import get_session
from app.deps import get_retriever, get_session_factory, require_roles
from app.guardrails.pii import redact_pii
from app.rag.chunking import load_sops, read_field
from app.rag.indexer import index_sops
from app.rag.retriever import HybridRetriever
from app.tools.executor import audit

logger = logging.getLogger("aihas")
router = APIRouter(tags=["kb-admin"])

MAX_TEXT = 20_000
BLOCKED_KINDS = ("GOV_ID", "CARD", "SECRET", "OTP")
BLOCKED_TAGS = ("[GOV_ID]", "[CARD]", "[SECRET]", "[OTP]")
SOP_ID = re.compile(r"^KB-(\d{3})$")
_write_lock = threading.Lock()   # two admins adding at once must not get the same ID


class NewSop(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    category: str = Field(min_length=1, max_length=100)
    applies_to: str = Field(default="", max_length=200)
    escalation: str = Field(default="", max_length=200)
    body: str = Field(min_length=10, max_length=MAX_TEXT)   # Markdown: "Steps:", numbered lines, "Notes:"


class SopText(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT + 1000)


def kb_path() -> Path:
    path = Path(settings.kb_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def secret_hits(text: str) -> int:
    redacted, _ = redact_pii(text, kinds=BLOCKED_KINDS)
    return sum(redacted.count(tag) for tag in BLOCKED_TAGS)


def refuse_secrets(new_text: str, old_text: str = "") -> None:
    # An edit is only refused for secrets it ADDS, so an old SOP that already trips the filter can still be edited.
    if secret_hits(new_text) > secret_hits(old_text):
        raise HTTPException(
            status_code=400,
            detail="This text looks like it contains a password, one-time code, card number or government ID. "
                   "Remove it. SOPs are visible to every employee.")


def one_line(value: str, label: str) -> str:
    value = value.strip()
    if "\n" in value or "\r" in value:
        raise HTTPException(status_code=400, detail=f"{label} must be a single line.")
    return value


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50] or "sop"


ARCHIVE = ".deleted"


def next_number(folder: Path) -> int:
    # Deleted SOPs count too, so an ID is never reused: old chats still cite it
    names = [p.name for p in folder.glob("KB-*.md")] + [p.name for p in (folder / ARCHIVE).glob("KB-*.md")]
    numbers = [int(m.group(1)) for n in names if (m := re.match(r"KB-(\d{3})", n))]
    numbers += [int(m.group(1)) for s in load_sops(str(folder)) if (m := SOP_ID.match(s["sop_id"]))]
    return max(numbers, default=0) + 1


def compose(sop_id: str, body: NewSop) -> str:
    title = one_line(body.title, "Title").lstrip("# ").strip()
    category = one_line(body.category, "Category")
    applies_to = one_line(body.applies_to, "Applies to")
    escalation = one_line(body.escalation, "Escalation")
    if not title or not category:
        raise HTTPException(status_code=400, detail="Enter a title and a category.")
    lines = [f"# {title}", f"SOP ID: {sop_id}", f"Category: {category}"]
    if applies_to:
        lines.append(f"Applies to: {applies_to}")
    if escalation:
        lines.append(f"Escalation: {escalation}")
    text = "\n".join(lines) + "\n\n" + body.body.replace("\r\n", "\n").strip() + "\n"
    return text


def index_now(retriever: HybridRetriever, factory) -> tuple[bool, dict | None]:
    """Index changed SOPs and reload the keyword index. Returns (ok, summary)."""
    try:
        summary = index_sops(force=False, embed_model=retriever.embed_model, collection=retriever.collection,
                             session_factory=factory)
        retriever.reload()
        return True, summary
    except Exception as exc:
        logger.warning("SOP saved but indexing failed: %s", type(exc).__name__)
        return False, None


def result(sop_id: str, title: str, category: str, filename: str, indexed: bool, summary: dict | None) -> dict:
    out = {"sop_id": sop_id, "title": title, "category": category, "filename": filename,
           "indexed": indexed, "index": summary}
    if not indexed:
        out["warning"] = "Saved, but indexing failed. Check that Ollama and ChromaDB are running, then click Re-index."
    return out


@router.post("/kb", status_code=201)
def add_sop(body: NewSop, admin: User = Depends(require_roles("admin")), session=Depends(get_session),
            retriever: HybridRetriever = Depends(get_retriever), factory=Depends(get_session_factory)):
    folder = kb_path()
    with _write_lock:
        number = next_number(folder)
        if number > 999:
            raise HTTPException(status_code=400, detail="The knowledge base is full (KB-999).")
        sop_id = f"KB-{number:03d}"
        text = compose(sop_id, body)
        if len(text) > MAX_TEXT:
            raise HTTPException(status_code=400, detail=f"The SOP is too long. Keep it under {MAX_TEXT} characters.")
        refuse_secrets(text)
        filename = f"{sop_id}-{slug(body.title)}.md"
        try:
            with open(folder / filename, "x", encoding="utf-8", newline="\n") as handle:   # "x": never overwrite
                handle.write(text)
        except FileExistsError:
            raise HTTPException(status_code=409, detail="That SOP file already exists. Try again.")
    audit(session, admin.id, "kb.created", "kb_document", number)
    session.commit()
    indexed, summary = index_now(retriever, factory)
    title = text.splitlines()[0].lstrip("# ").strip()
    return result(sop_id, title, body.category.strip(), filename, indexed, summary)


def find_file(folder: Path, sop_id: str) -> Path | None:
    for path in sorted(folder.glob("KB-*.md")):
        if read_field(path.read_text(encoding="utf-8"), "SOP ID") == sop_id:
            return path
    return None


@router.put("/kb/{sop_id}")
def edit_sop(sop_id: str, body: SopText, admin: User = Depends(require_roles("admin")),
             session=Depends(get_session), retriever: HybridRetriever = Depends(get_retriever),
             factory=Depends(get_session_factory)):
    match = SOP_ID.match(sop_id)
    if not match:
        raise HTTPException(status_code=404, detail="SOP not found")
    folder = kb_path()
    with _write_lock:
        path = find_file(folder, sop_id)
        if path is None:
            raise HTTPException(status_code=404, detail="SOP not found")

        text = body.text.lstrip("\ufeff").replace("\r\n", "\n").strip() + "\n"
        lines = text.splitlines()
        if len(text) > MAX_TEXT:
            raise HTTPException(status_code=400, detail=f"The SOP is too long. Keep it under {MAX_TEXT} characters.")
        if not lines[0].startswith("# ") or not lines[0][2:].strip():
            raise HTTPException(status_code=400, detail="The first line must be the title, starting with '# '.")
        if read_field(text, "SOP ID") != sop_id:
            raise HTTPException(status_code=400, detail=f"Keep the line 'SOP ID: {sop_id}' unchanged.")
        if not read_field(text, "Category"):
            raise HTTPException(status_code=400, detail="Keep a 'Category:' line with a value.")
        refuse_secrets(text, path.read_text(encoding="utf-8"))

        # Write to a temporary file and swap it in, so a crash never leaves half an SOP behind
        fd, tmp_name = tempfile.mkstemp(dir=folder, prefix=".sop-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
    audit(session, admin.id, "kb.updated", "kb_document", int(match.group(1)))
    session.commit()
    indexed, summary = index_now(retriever, factory)
    return result(sop_id, lines[0][2:].strip(), read_field(text, "Category"), path.name, indexed, summary)


def referenced_by(folder: Path, sop_id: str) -> list[dict]:
    pattern = re.compile(rf"\b{re.escape(sop_id)}\b")
    return [{"sop_id": other["sop_id"], "title": other["title"]}
            for other in load_sops(str(folder)) if other["sop_id"] != sop_id and pattern.search(other["text"])]


@router.get("/kb/{sop_id}/references")
def sop_references(sop_id: str, admin: User = Depends(require_roles("admin"))):
    if not SOP_ID.match(sop_id) or find_file(kb_path(), sop_id) is None:
        raise HTTPException(status_code=404, detail="SOP not found")
    return {"sop_id": sop_id, "referenced_by": referenced_by(kb_path(), sop_id)}


@router.delete("/kb/{sop_id}")
def delete_sop(sop_id: str, admin: User = Depends(require_roles("admin")), session=Depends(get_session),
               retriever: HybridRetriever = Depends(get_retriever)):
    match = SOP_ID.match(sop_id)
    if not match:
        raise HTTPException(status_code=404, detail="SOP not found")
    folder = kb_path()
    with _write_lock:
        path = find_file(folder, sop_id)
        if path is None:
            raise HTTPException(status_code=404, detail="SOP not found")
        if len(load_sops(str(folder))) <= 1:
            raise HTTPException(status_code=400, detail="This is the last SOP. The assistant needs at least one.")
        title = path.read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip()
        others = referenced_by(folder, sop_id)
        archive = folder / ARCHIVE
        archive.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archived = archive / f"{path.stem}-{stamp}.md"
        shutil.move(str(path), str(archived))   # a move, not a delete: restore by moving it back
    audit(session, admin.id, "kb.deleted", "kb_document", int(match.group(1)))
    session.commit()

    out = {"sop_id": sop_id, "title": title, "archived_as": f"{ARCHIVE}/{archived.name}", "referenced_by": others,
           "search_updated": True}
    try:
        retriever.collection.delete(where={"sop_id": sop_id})
        retriever.reload()
    except Exception as exc:
        logger.warning("SOP deleted but the search index was not cleaned: %s", type(exc).__name__)
        out["search_updated"] = False
        out["warning"] = "Deleted, but the search index still has old chunks. Click Re-index to clean them up."
    return out
