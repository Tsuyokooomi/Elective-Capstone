# Chat Interface, Agent Queue, and Dashboard

The web interface is a Streamlit app in `frontend/`. It runs as its own container and calls the API over HTTP.

Open it at http://localhost:8501.

## Sign-in (temporary)

The sidebar has a "Sign in as (demo)" list with three accounts. The frontend sends the chosen employee ID in an `X-Employee-Id` header, and the API checks the role. Phase 5 replaces this with a real login and tokens. The role checks stay as they are.

| Account | Role | Screens |
|---|---|---|
| E-1001 Alex Employee | employee | Chat |
| E-2001 Ana Agent | agent | Agent queue, Chat |
| E-3001 Adam Admin | admin | Dashboard, Agent queue, Knowledge base, Chat |

## Screens

**Chat.** The employee describes a problem. The assistant answers with the cited SOPs, asks YES or NO before a password reset or a ticket (with buttons), and shows the ticket number after an escalation. A "Details" box under each answer shows the intent, route, tool, whether the model or the fallback chose the tool arguments, and the latency. Past chats can be reopened from the sidebar. The reply appears word by word. This is a display effect, not token streaming from the model.

**Agent queue.** Tickets are sorted by priority (P1 first). An agent opens a ticket, reads the whole conversation, assigns the ticket to themselves, replies to the employee, and resolves, closes, or reopens the ticket. After an agent claims a ticket, the assistant stops answering in that chat, and the employee's new messages wait for the agent.

**Dashboard.** Numbers from `GET /metrics/summary`:

| Metric | Meaning |
|---|---|
| Ticket deflection | Share of chats the assistant resolved: the user said thanks after an answer, and no ticket or agent was involved |
| Escalation rate | Share of chats handed to a human |
| MTTR | Mean time from ticket creation to resolution, in minutes |
| Latency (avg, p50, p95) | Time the assistant took per reply |
| Blocked messages | Messages stopped by the injection check |

The page also shows messages per day, intents, tickets by priority, tool calls, and the latest audit log.

**Knowledge base.** Lists the SOPs and whether each one is indexed. An admin can preview an SOP, re-index changed files, or rebuild everything.

## Endpoints added in this phase

| Endpoint | Who can use it |
|---|---|
| GET `/me` | Anyone signed in |
| GET `/conversations`, GET `/conversations/{id}/messages` | Employees see their own chats. Staff see all. |
| POST `/conversations/{id}/agent-reply` | Agent, admin |
| GET `/tickets`, GET `/tickets/{id}` | Employees see their own tickets. Staff see all. |
| PATCH `/tickets/{id}` | Agent, admin |
| GET `/metrics/summary` | Agent, admin |
| GET `/audit-logs` | Admin |
| GET `/kb`, GET `/kb/{sop_id}` | Anyone signed in |
| POST `/kb/reindex` | Admin |

## Tests

```
docker compose exec api python -m pytest tests -q
docker compose exec frontend python -m pytest tests -q
```
