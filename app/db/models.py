from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# Allowed values (kept as plain strings in the database)
ROLES = ("employee", "agent", "admin")
CONVERSATION_STATUSES = ("open", "resolved", "escalated")
SENDERS = ("user", "assistant", "agent", "system")
TICKET_PRIORITIES = ("P1", "P2", "P3", "P4")
TICKET_STATUSES = ("open", "in_progress", "resolved", "closed")
TOOL_STATUSES = ("pending_confirmation", "confirmed", "completed", "failed", "cancelled")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    role: Mapped[str] = mapped_column(String(20), default="employee")
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="user")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="open")
    resolved_by_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))
    sender: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)  # store after PII redaction
    intent: Mapped[str | None] = mapped_column(String(50), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
    sources: Mapped[list["MessageSource"]] = relationship(back_populates="message")
    tool_calls: Mapped[list["ToolCall"]] = relationship(back_populates="message")


class KBDocument(Base):
    __tablename__ = "kb_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    sop_id: Mapped[str] = mapped_column(String(20), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(100))
    checksum: Mapped[str] = mapped_column(String(64))
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MessageSource(Base):
    __tablename__ = "message_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"))
    kb_document_id: Mapped[int] = mapped_column(ForeignKey("kb_documents.id"))
    chunk_ref: Mapped[str] = mapped_column(String(100))
    score: Mapped[float] = mapped_column(Float)

    message: Mapped["Message"] = relationship(back_populates="sources")
    kb_document: Mapped["KBDocument"] = relationship()


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"))
    tool_name: Mapped[str] = mapped_column(String(50))
    arguments: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending_confirmation")
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    message: Mapped["Message"] = relationship(back_populates="tool_calls")


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    priority: Mapped[str] = mapped_column(String(2), default="P3")
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    requester: Mapped["User"] = relationship(foreign_keys=[user_id])
    assignee: Mapped["User | None"] = relationship(foreign_keys=[assigned_to])


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)