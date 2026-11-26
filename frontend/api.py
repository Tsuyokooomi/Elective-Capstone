"""A thin client for the backend API. Every call goes through request()."""
import os

import requests

API_URL = os.getenv("API_URL", "http://localhost:8080")


class ApiError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def request(method: str, path: str, token: str | None = None, **kwargs):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    kwargs.setdefault("timeout", 180)
    try:
        response = requests.request(method, API_URL + path, headers=headers, **kwargs)
    except requests.RequestException:
        raise ApiError(f"Cannot reach the API at {API_URL}. Is the api container running?")
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise ApiError(str(detail), response.status_code)
    return response.json()


def login(employee_id, password):
    """Returns {"access_token", "user", ...}. Raises ApiError(401) for a wrong ID or password, 429 when locked."""
    return request("POST", "/auth/login", None, json={"employee_id": employee_id, "password": password})


def reset_password(reset_token, new_password):
    """Set a new password using the one-time token from the reset link."""
    return request("POST", "/auth/reset-password", None, json={"token": reset_token, "new_password": new_password})


def outbox(token):
    """Admin only: the fake email service's sent messages."""
    return request("GET", "/mock/outbox", token)


def users(token):
    """Admin only: every account (no passwords)."""
    return request("GET", "/users", token)


def create_user(token, employee_id, name, email, role, password):
    """Admin only: create an account. Raises ApiError(400) for bad input, 409 for a duplicate."""
    return request("POST", "/users", token, json={
        "employee_id": employee_id, "name": name, "email": email, "role": role, "password": password})


def chat(token, message, conversation_id=None):
    # Who is asking comes from the token. The backend ignores any employee ID in the body.
    return request("POST", "/chat", token, json={"message": message, "conversation_id": conversation_id})


def conversations(token, status=None):
    return request("GET", "/conversations", token, params={"status": status} if status else None)


def conversation_messages(token, conversation_id):
    return request("GET", f"/conversations/{conversation_id}/messages", token)


def tickets(token, status=None):
    return request("GET", "/tickets", token, params={"status": status} if status else None)


def update_ticket(token, ticket_id, **changes):
    return request("PATCH", f"/tickets/{ticket_id}", token, json=changes)


def agent_reply(token, conversation_id, message):
    return request("POST", f"/conversations/{conversation_id}/agent-reply", token, json={"message": message})


def metrics(token):
    return request("GET", "/metrics/summary", token)


def audit_logs(token, limit=50):
    return request("GET", "/audit-logs", token, params={"limit": limit})


def kb_list(token):
    return request("GET", "/kb", token)


def kb_doc(token, sop_id):
    return request("GET", f"/kb/{sop_id}", token)


def kb_create(token, title, category, body, applies_to="", escalation=""):
    """Admin only: add a new SOP. The reply says whether it was indexed."""
    return request("POST", "/kb", token, json={
        "title": title, "category": category, "body": body, "applies_to": applies_to, "escalation": escalation})


def kb_update(token, sop_id, text):
    """Admin only: replace the full text of an SOP."""
    return request("PUT", f"/kb/{sop_id}", token, json={"text": text})


def kb_references(token, sop_id):
    """Admin only: which other SOPs mention this one."""
    return request("GET", f"/kb/{sop_id}/references", token)


def kb_delete(token, sop_id):
    """Admin only: archive an SOP and remove it from search."""
    return request("DELETE", f"/kb/{sop_id}", token)


def kb_reindex(token, force=False):
    return request("POST", "/kb/reindex", token, params={"force": force})


def health():
    """Used for the online indicator in the sidebar."""
    return request("GET", "/health", None, timeout=3)
