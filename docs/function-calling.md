# Function Calling and Automation

## Tools

| Tool | What it does | Who calls it | Needs confirmation |
|---|---|---|---|
| `reset_password` | Starts a password reset for the signed-in employee: emails a one-time link (mock email service). The password changes only when the employee uses the link | The LLM, for the `password_reset` intent | Yes |
| `create_ticket` | Opens a ticket (mock Jira or ServiceNow) | The LLM, for `access_request` and `hardware_request` | Yes |
| `escalate_to_human` | Opens a ticket and marks the chat as escalated | The system, for `security_incident`, `mfa_lost`, and `human_request` | No |

The tool schemas live in `app/tools/definitions.py`. LlamaIndex builds each schema from the function signature and docstring.

## Flow for an action

1. The classifier sets the intent, for example `access_request`.
2. The LLM sees only the tools that fit that intent and chooses one with its arguments (`chat_with_tools`).
3. The code checks the arguments. Bad values are replaced by safe defaults and unknown keys are dropped.
4. The assistant shows what it will do and asks for YES or NO. A `tool_calls` row is saved with status `pending_confirmation`.
5. The next message is read by a simple rule, not the LLM:
   - YES: the action runs, the row becomes `completed`, and a webhook event is sent.
   - NO: the row becomes `cancelled`.
   - Anything else: the pending request is cancelled and the message is handled as a new request.

If the model fails or makes no tool call, the code uses default arguments. The response field `tool_source` shows `llm` or `fallback`.

## Safety controls

- **Identity comes from the session.** No tool takes an employee ID. The LLM cannot act for another person.
- **The LLM cannot raise urgency.** For `create_ticket`, only P3 and P4 are valid. P1 and P2 come only from the rule-based escalation.
- **Confirmation before any change.**
- **Reset limit.** At most 3 resets per user per hour (`MAX_RESETS_PER_HOUR`).
- **No secrets in chat.** The mock reset sets a random password and only reports a masked email address.
- **One open ticket per escalated chat.** A new, more urgent case raises the priority of the open ticket.
- **Audit log.** Every step writes a row.

## Audit actions

`tool.proposed`, `tool.confirmed`, `tool.completed`, `tool.failed`, `tool.cancelled`, `ticket.created`, `ticket.priority_raised`, `chat.escalated`, `guardrail.blocked`, `auth.login_ok`, `auth.login_failed`, `auth.password_reset`.

## Webhooks

After a ticket is created, an escalation opens, or a reset completes, the system sends a JSON event to `WEBHOOK_URL` (for example an n8n webhook). Events: `ticket.created`, `ticket.escalated`, `password_reset.requested` (the link was emailed), `password_reset.completed` (the employee chose a new password). The payload holds no passwords, no reset tokens and no message text. A failed webhook never breaks the chat.

For a demo without n8n, set `WEBHOOK_URL=http://localhost:8080/mock/webhook`. The events show at `GET /mock/webhook/events`.

## Endpoints added

| Method and path | Purpose |
|---|---|
| GET `/tickets` | List tickets (`?status=open`) |
| GET `/tickets/{id}` | One ticket |
| GET `/audit-logs` | Latest audit rows (admin only) |
| POST `/mock/webhook` | Demo webhook receiver. If `WEBHOOK_SECRET` is set, the sender must send it in `X-Webhook-Secret` |
| GET `/mock/webhook/events` | Events the receiver got (admin only) |
| GET `/mock/outbox` | The fake email service's sent messages, including reset links (admin only) |

All of these now need a login token, and most need a role. See [authentication.md](authentication.md).

## Ticket priorities (KB-019)

| Priority | Used for | First response |
|---|---|---|
| P1 | Security incidents | 15 minutes |
| P2 | Lost MFA device | 1 hour |
| P3 | Human request, hardware request | 4 hours |
| P4 | Access request | 1 business day |
