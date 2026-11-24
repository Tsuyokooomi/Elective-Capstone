from pydantic import BaseModel, Field


class ChatBody(BaseModel):
    """What a client may send to POST /chat. Who is asking comes from the sign-in token, never from the body."""
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: int | None = None


class ChatRequest(BaseModel):
    """Internal request for handle_chat. The API fills employee_id from the signed-in user."""
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: int | None = None
    employee_id: str = "E-1001"


class SourceOut(BaseModel):
    sop_id: str
    title: str
    chunk_id: str
    score: float


class ChatResponse(BaseModel):
    conversation_id: int
    message_id: int | None   # None when a human agent is handling the chat
    reply: str
    intent: str | None
    confidence: float | None
    route: str                  # answer, action, escalate, decline, or blocked
    tool: str | None            # tool that Phase 3 will run for this intent
    sources: list[SourceOut]
    grounded: bool
    invalid_citations: list[str] = []   # SOP ids the model cited but were not retrieved
    escalated: bool
    agent_handling: bool = False   # a human agent has taken over: the bot stays silent
    pending_confirmation: bool = False   # waiting for the user to reply YES or NO
    ticket_key: str | None = None
    tool_result: dict | None = None
    tool_source: str | None = None   # "llm" if the model chose the tool arguments, "fallback" if not
    pii_redacted: bool
    guardrail_flags: list[str] = []   # what the output filter changed in the reply, if anything
    latency_ms: int
