"""Tool definitions shown to the LLM. LlamaIndex turns each function's signature and
docstring into a tool schema. The functions are never run by the LLM: our code checks the
arguments, asks the user to confirm, and then runs the real action (see executor.py)."""
from llama_index.core.tools import FunctionTool

TICKET_CATEGORIES = ("access", "hardware", "software", "network", "other")


def reset_password(reason: str = "") -> str:
    """Start a password reset for the signed-in employee. Use it when the user forgot
    their password or asks for a reset. The employee is taken from the session, so never
    pass an employee ID. reason: a few words from the user, or empty."""
    return "pending"


def create_ticket(title: str, description: str, category: str, priority: str = "P4") -> str:
    """Open an IT support ticket for the signed-in employee. title: a short summary under
    80 characters. description: what the user needs, in one or two sentences. category: one
    of access, hardware, software, network, other. priority: P3 if the user cannot work
    without it, otherwise P4."""
    return "pending"


def escalate_to_human(reason: str, priority: str = "P3") -> str:
    """Hand the chat to a human agent and open a ticket. The system calls this itself for
    security incidents, lost MFA devices, and requests for a person."""
    return "pending"


TOOLS = {
    "reset_password": FunctionTool.from_defaults(fn=reset_password, name="reset_password"),
    "create_ticket": FunctionTool.from_defaults(fn=create_ticket, name="create_ticket"),
    "escalate_to_human": FunctionTool.from_defaults(fn=escalate_to_human, name="escalate_to_human"),
}

# The LLM only sees the tools that fit the classified intent.
ALLOWED_BY_INTENT = {
    "password_reset": ["reset_password"],
    "access_request": ["create_ticket"],
    "hardware_request": ["create_ticket"],
}
