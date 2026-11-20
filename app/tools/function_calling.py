import logging
from dataclasses import dataclass

from llama_index.core.llms import ChatMessage

from app.rag.prompts import COMPANY, PRIORITY_BY_INTENT
from app.tools.definitions import ALLOWED_BY_INTENT, TICKET_CATEGORIES, TOOLS

logger = logging.getLogger("aihas.tools")

SYSTEM_PROMPT = (
    f"You help employees of {COMPANY} with IT support. Call exactly one tool that fits the "
    "request. Fill the arguments from the user's own words. Never invent details."
)

CATEGORY_BY_INTENT = {"access_request": "access", "hardware_request": "hardware"}
TICKET_PRIORITIES = ("P3", "P4")   # the LLM may not raise a ticket above P3


@dataclass
class ToolChoice:
    name: str
    args: dict
    source: str   # "llm" if the model chose the arguments, "fallback" if our defaults were used


def _one_line(text: str, limit: int) -> str:
    return " ".join(str(text).split())[:limit]


def default_args(name: str, intent: str, message: str) -> dict:
    if name == "reset_password":
        return {"reason": ""}
    priority = PRIORITY_BY_INTENT.get(intent, "P4")
    return {
        "title": _one_line(message, 80) or "IT support request",
        "description": _one_line(message, 500),
        "category": CATEGORY_BY_INTENT.get(intent, "other"),
        "priority": priority if priority in TICKET_PRIORITIES else "P4",
    }


def sanitize_args(name: str, raw: dict, intent: str, message: str) -> dict:
    """Check what the LLM sent. Wrong or missing values are replaced by safe defaults.
    Unknown keys, such as an employee ID, are dropped."""
    defaults = default_args(name, intent, message)
    raw = raw or {}
    if name == "reset_password":
        return {"reason": _one_line(raw.get("reason", ""), 200)}
    title = _one_line(raw.get("title", ""), 80)
    description = _one_line(raw.get("description", ""), 500)
    category = str(raw.get("category", "")).lower()
    priority = str(raw.get("priority", "")).upper()
    return {
        "title": title or defaults["title"],
        "description": description or defaults["description"],
        "category": category if category in TICKET_CATEGORIES else defaults["category"],
        "priority": priority if priority in TICKET_PRIORITIES else defaults["priority"],
    }


def choose_tool(llm, intent: str, message: str) -> ToolChoice | None:
    """Let the LLM pick a tool and fill its arguments. Fall back to defaults if it fails."""
    names = ALLOWED_BY_INTENT.get(intent)
    if not names:
        return None
    fallback = ToolChoice(names[0], default_args(names[0], intent, message), "fallback")
    if llm is None:
        return fallback
    try:
        response = llm.chat_with_tools(
            [TOOLS[n] for n in names],
            user_msg=message,
            chat_history=[ChatMessage(role="system", content=SYSTEM_PROMPT)],
            tool_required=True,
        )
        calls = llm.get_tool_calls_from_response(response, error_on_no_tool_call=False)
        for call in calls:
            if call.tool_name in names:
                args = sanitize_args(call.tool_name, dict(call.tool_kwargs or {}), intent, message)
                return ToolChoice(call.tool_name, args, "llm")
    except Exception:
        logger.exception("tool calling failed, using defaults")
    return fallback
