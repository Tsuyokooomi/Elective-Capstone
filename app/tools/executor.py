"""Runs the real actions behind the tools. The mock services here stand in for the email
service (password reset links) and Jira or ServiceNow (tickets)."""
import re
from datetime import timedelta

from sqlalchemy import func, select

from app.auth import create_reset_token
from app.config import settings
from app.db.models import AuditLog, Conversation, Message, Ticket, ToolCall, User, utcnow
from app.tools.mock_email import send_reset_email

YES = {"yes", "y", "yep", "yeah", "yup", "confirm", "confirmed", "ok", "okay", "sure", "proceed",
       "go ahead", "yes please", "please do", "sige", "oo", "opo", "yes po", "oo po", "sige po"}
NO = {"no", "n", "nope", "cancel", "stop", "dont", "don't", "do not", "no thanks", "no thank you",
      "hindi", "huwag", "wag", "hindi po", "cancel it"}

FIRST_RESPONSE = {"P1": "15 minutes", "P2": "1 hour", "P3": "4 hours", "P4": "1 business day"}  # KB-019

CONFIRM_TICKET_MESSAGE = (
    "I will open this ticket:\n- Title: {title}\n- Category: {category}\n- Priority: {priority}\n"
    "Reply YES to confirm, or NO to cancel."
)
TICKET_CREATED_MESSAGE = (
    "Done. Your ticket {key} is open with priority {priority}. "
    "The first response is due within {sla}."
)
RESET_DONE_MESSAGE = (
    "Done. I sent a password reset link to {email}. The link expires in {minutes} minutes. "
    "See KB-001 for the next steps."
)
RESET_LIMIT_MESSAGE = (
    "You have reached the limit of {limit} password resets in one hour. "
    "Please ask a human agent for help, or try again later."
)
CANCELLED_MESSAGE = "OK, I cancelled that request. What else can I help you with?"
ESCALATION_REUSED_MESSAGE = (
    "A human agent has already been requested. Your ticket is {ticket_id} (priority {priority})."
)


class ToolError(Exception):
    pass


def parse_confirmation(text: str) -> str | None:
    """Return "yes", "no", or None if the message is neither."""
    cleaned = re.sub(r"[^\w\s']", "", text.lower()).strip()
    cleaned = " ".join(cleaned.split())
    if cleaned in YES:
        return "yes"
    if cleaned in NO:
        return "no"
    return None


def ticket_key(ticket_id: int) -> str:
    return f"CC-{ticket_id:04d}"


def mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:1]}***@{domain}"


def audit(session, user_id, action: str, entity_type: str, entity_id) -> None:
    session.add(AuditLog(user_id=user_id, action=action, entity_type=entity_type, entity_id=entity_id))


def find_pending(session, conversation_id: int) -> ToolCall | None:
    stmt = (
        select(ToolCall)
        .join(Message, ToolCall.message_id == Message.id)
        .where(Message.conversation_id == conversation_id, ToolCall.status == "pending_confirmation")
        .order_by(ToolCall.id.desc())
    )
    return session.scalars(stmt).first()


def count_recent_resets(session, user_id: int) -> int:
    cutoff = utcnow() - timedelta(hours=1)
    stmt = (
        select(func.count())
        .select_from(ToolCall)
        .join(Message, ToolCall.message_id == Message.id)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Conversation.user_id == user_id,
            ToolCall.tool_name == "reset_password",
            ToolCall.status == "completed",
            ToolCall.confirmed_at >= cutoff,
        )
    )
    return session.scalar(stmt) or 0


def find_open_ticket(session, conversation_id: int) -> Ticket | None:
    stmt = (
        select(Ticket)
        .where(Ticket.conversation_id == conversation_id, Ticket.status.in_(("open", "in_progress")))
        .order_by(Ticket.id)
    )
    return session.scalars(stmt).first()


def create_ticket_row(session, user, conversation, title: str, priority: str) -> Ticket:
    ticket = Ticket(user_id=user.id, conversation_id=conversation.id, title=title[:200], priority=priority)
    session.add(ticket)
    session.flush()
    audit(session, user.id, "ticket.created", "ticket", ticket.id)
    return ticket


def escalate(session, user, conversation, reason: str, priority: str) -> tuple[Ticket, bool]:
    """Open a ticket for a human agent. Returns (ticket, created). One open ticket per chat."""
    existing = find_open_ticket(session, conversation.id)
    conversation.status = "escalated"
    if existing is not None:
        if priority < existing.priority:          # "P1" < "P4": the new case is more urgent
            existing.priority = priority
            audit(session, user.id, "ticket.priority_raised", "ticket", existing.id)
        return existing, False
    ticket = create_ticket_row(session, user, conversation, f"Escalation: {reason}", priority)
    audit(session, user.id, "chat.escalated", "conversation", conversation.id)
    return ticket, True


def cancel_tool_call(session, tool_call, user, status_note: str) -> None:
    tool_call.status = "cancelled"
    tool_call.result = {"note": status_note}
    audit(session, user.id, "tool.cancelled", "tool_call", tool_call.id)


def execute_tool_call(session, tool_call, user, conversation) -> tuple[dict, list[tuple[str, dict]]]:
    """Run a confirmed tool call. Returns (result, webhook events)."""
    args = (tool_call.arguments or {}).get("args", {})
    events: list[tuple[str, dict]] = []
    try:
        if tool_call.tool_name == "reset_password":
            if count_recent_resets(session, user.id) >= settings.max_resets_per_hour:
                raise ToolError(RESET_LIMIT_MESSAGE.format(limit=settings.max_resets_per_hour))
            # Mock email service: the user gets a one-time link and chooses the new password
            # themselves (POST /auth/reset-password). The current password stays valid until then.
            # The token goes only into the email. It is never put in the result, chat reply or webhook.
            token = create_reset_token(user.employee_id, user.password_hash)
            link = f"{settings.frontend_url.rstrip('/')}/?reset_token={token}"
            send_reset_email(user.email, link, settings.reset_link_minutes)
            result = {"email": mask_email(user.email), "expires_in_minutes": settings.reset_link_minutes}
            events.append(("password_reset.requested", {"employee_id": user.employee_id}))
        elif tool_call.tool_name == "create_ticket":
            ticket = create_ticket_row(session, user, conversation, args["title"], args["priority"])
            result = {"ticket_id": ticket.id, "ticket_key": ticket_key(ticket.id), "priority": ticket.priority}
            events.append(("ticket.created", {"ticket_key": result["ticket_key"], "priority": ticket.priority,
                                              "category": args["category"], "employee_id": user.employee_id}))
        else:
            raise ToolError(f"Unknown tool: {tool_call.tool_name}")
    except ToolError as exc:
        tool_call.status = "failed"
        tool_call.result = {"error": str(exc)}
        audit(session, user.id, "tool.failed", "tool_call", tool_call.id)
        raise
    tool_call.status = "completed"
    tool_call.result = result
    audit(session, user.id, "tool.completed", "tool_call", tool_call.id)
    return result, events
