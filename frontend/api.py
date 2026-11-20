"""A thin client for the backend API. Every call goes through request()."""
import os

import requests

API_URL = os.getenv("API_URL", "http://localhost:8080")


class ApiError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def request(method: str, path: str, employee_id: str | None = None, **kwargs):
    # Placeholder sign-in: the backend reads X-Employee-Id. Phase 5 replaces it with tokens.
    headers = {"X-Employee-Id": employee_id} if employee_id else {}
    try:
        response = requests.request(method, API_URL + path, headers=headers, timeout=180, **kwargs)
    except requests.RequestException:
        raise ApiError(f"Cannot reach the API at {API_URL}. Is the api container running?")
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise ApiError(str(detail), response.status_code)
    return response.json()


def chat(employee_id, message, conversation_id=None):
    return request("POST", "/chat", employee_id,
                   json={"message": message, "conversation_id": conversation_id, "employee_id": employee_id})


def conversations(employee_id, status=None):
    return request("GET", "/conversations", employee_id, params={"status": status} if status else None)


def conversation_messages(employee_id, conversation_id):
    return request("GET", f"/conversations/{conversation_id}/messages", employee_id)


def tickets(employee_id, status=None):
    return request("GET", "/tickets", employee_id, params={"status": status} if status else None)


def update_ticket(employee_id, ticket_id, **changes):
    return request("PATCH", f"/tickets/{ticket_id}", employee_id, json=changes)


def agent_reply(employee_id, conversation_id, message):
    return request("POST", f"/conversations/{conversation_id}/agent-reply", employee_id, json={"message": message})


def metrics(employee_id):
    return request("GET", "/metrics/summary", employee_id)


def audit_logs(employee_id, limit=50):
    return request("GET", "/audit-logs", employee_id, params={"limit": limit})


def kb_list(employee_id):
    return request("GET", "/kb", employee_id)


def kb_doc(employee_id, sop_id):
    return request("GET", f"/kb/{sop_id}", employee_id)


def kb_reindex(employee_id, force=False):
    return request("POST", "/kb/reindex", employee_id, params={"force": force})
