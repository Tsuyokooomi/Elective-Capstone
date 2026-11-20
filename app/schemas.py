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
    invalid_citations: list[str] = []   # SOP ids the model cited but were not retrieved
    escalated: bool
    pending_confirmation: bool = False   # waiting for the user to reply YES or NO
    ticket_key: str | None = None
    tool_result: dict | None = None
    tool_source: str | None = None   # "llm" if the model chose the tool arguments, "fallback" if not
    pii_redacted: bool
    latency_ms: int
