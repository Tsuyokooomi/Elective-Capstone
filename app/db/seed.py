"""Create tables, add demo users, and register the KB files.

Run from the project root:
    python -m app.db.seed
In Docker:
    docker compose exec api python -m app.db.seed
"""
import hashlib
from pathlib import Path

from sqlalchemy import select

from app.db.models import KBDocument, User
from app.db.security import hash_password
from app.db.session import SessionLocal, init_db

KB_DIR = Path("kb")

# Demo accounts only. These are fake and must never be reused anywhere else.
DEMO_USERS = [
    ("E-1001", "Alex Employee", "alex@capstonecompany.example", "employee", "Demo-Employee-123"),
    ("E-2001", "Ana Agent", "ana@capstonecompany.example", "agent", "Demo-Agent-123"),
    ("E-3001", "Adam Admin", "adam@capstonecompany.example", "admin", "Demo-Admin-123"),
]


def seed_users(session) -> int:
    added = 0
    for employee_id, name, email, role, password in DEMO_USERS:
        exists = session.scalar(select(User).where(User.employee_id == employee_id))
        if exists:
            continue
        session.add(
            User(
                employee_id=employee_id,
                name=name,
                email=email,
                role=role,
                password_hash=hash_password(password),
            )
        )
        added += 1
    return added


def read_field(text: str, label: str) -> str:
    for line in text.splitlines():
        if line.startswith(f"{label}:"):
            return line.split(":", 1)[1].strip()
    return ""


def seed_kb(session) -> tuple[int, int]:
    added = updated = 0
    for path in sorted(KB_DIR.glob("KB-*.md")):
        text = path.read_text(encoding="utf-8")
        sop_id = read_field(text, "SOP ID")
        if not sop_id:
            continue
        title = text.splitlines()[0].lstrip("# ").strip()
        category = read_field(text, "Category")
        checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()

        doc = session.scalar(select(KBDocument).where(KBDocument.sop_id == sop_id))
        if doc is None:
            session.add(KBDocument(sop_id=sop_id, title=title, category=category, checksum=checksum))
            added += 1
        elif doc.checksum != checksum:
            doc.title, doc.category, doc.checksum = title, category, checksum
            doc.indexed_at = None  # file changed, so it needs re-indexing
            updated += 1
    return added, updated


def main() -> None:
    init_db()
    with SessionLocal() as session:
        users_added = seed_users(session)
        kb_added, kb_updated = seed_kb(session)
        session.commit()
    print(f"Users added: {users_added}")
    print(f"KB documents added: {kb_added}, updated: {kb_updated}")


if __name__ == "__main__":
    main()