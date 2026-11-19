from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: int | None = None
    # Temporary: Phase 5 replaces this with real sign-in and roles.
    employee_id: str = "E-1001"


class SourceOut(BaseModel):
    sop_id: str
    title: str
    chunk_id: str
    score: float


class ChatResponse(BaseModel):
    conversation_id: int
    message_id: int
    reply: str
    intent: str | None
    confidence: float | None
    route: str                  # answer, action, escalate, decline, or blocked
    tool: str | None            # tool that Phase 3 will run for this intent
    sources: list[SourceOut]
    grounded: bool
    escalated: bool
    pii_redacted: bool
    latency_ms: int
