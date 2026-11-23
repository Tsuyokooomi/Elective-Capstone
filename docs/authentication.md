# Authentication and Roles (Phase 5A)

## How sign-in works

1. The user sends `POST /auth/login` with `employee_id` and `password`.
2. The API checks the password against the stored PBKDF2 hash (`app/db/security.py`).
3. On success it returns a **token**, a signed JWT that holds the employee ID and an expiry time.
4. The client sends `Authorization: Bearer <token>` on every other request.
5. `current_user()` in `app/deps.py` checks the signature and expiry, then loads the user from the database. `require_roles()` then checks the role.

The role is not stored in the token. It is read from the database on each request, so a role change or a deleted account takes effect at once.

## What changed from Phase 4

| Before | Now |
|---|---|
| Client sent `X-Employee-Id` and the API believed it | Client sends a signed token. A made-up ID does nothing |
| `POST /chat` took `employee_id` in the body | The body has only `message` and `conversation_id`. The employee is the token's owner |
| `GET /kb/search` was open | Agents and admins only |
| `GET /mock/webhook/events` was open | Admins only |
| `POST /mock/webhook` accepted anyone | Accepts only senders with `X-Webhook-Secret` when `WEBHOOK_SECRET` is set |

## Password reset (link flow)

1. The employee tells the assistant they forgot their password. The assistant asks for a YES, then runs the `reset_password` tool (limit: 3 per hour).
2. The tool creates a **reset token**: a signed JWT with `purpose = password_reset`, the employee ID, an expiry (`RESET_LINK_MINUTES`, default 15) and a **fingerprint of the current password hash**.
3. The token goes into a link, `FRONTEND_URL/?reset_token=...`, which is sent by the mock email service. The token is never put in the chat answer, the tool result, the database or the webhook.
4. The employee opens the link. The Streamlit app shows "Choose a new password" and calls `POST /auth/reset-password` with the token and the new password.
5. The API checks the signature, the expiry, the purpose and that the fingerprint still matches, then checks the password rules (at least 10 characters, a letter and a number, no employee ID inside, not the current password) and saves the new hash.

Why this is safe:

- **Single use without storage.** Changing the password changes the fingerprint, so the same link fails the second time.
- **The old password keeps working until the link is used.** Nobody can be locked out by someone else asking for a reset.
- **Reset and login tokens cannot be swapped.** A reset token never signs anyone in, and a login token never resets a password.
- A successful reset writes `auth.password_reset` to the audit log, sends the `password_reset.completed` webhook, and lifts a login lock on that account.

The mock email service keeps the last 20 messages in memory (lost on restart), prints each link to the API log, and shows them to admins at `GET /mock/outbox` and in the dashboard's "Mock email outbox" panel. A real deployment would replace `app/tools/mock_email.py` with SMTP or an n8n workflow. Admins can see live reset links in this demo outbox, which a real mail system would not allow.

## Settings (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `SECRET_KEY` | empty | Signs the tokens. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. If empty, a random key is made at every start, so everyone is signed out whenever the API restarts |
| `TOKEN_MINUTES` | 60 | How long a token is valid |
| `LOGIN_MAX_FAILURES` | 5 | Wrong passwords allowed per account inside the window |
| `LOGIN_LOCK_MINUTES` | 15 | The window, and roughly how long the lock lasts |
| `WEBHOOK_SECRET` | empty | Shared secret for the webhook receiver |
| `RESET_LINK_MINUTES` | 15 | How long a password reset link works |
| `FRONTEND_URL` | `http://localhost:8501` | Base of the link in the reset email |

## Password-guessing protection

- A wrong password writes `auth.login_failed` to the audit log. A success writes `auth.login_ok`.
- When an account has `LOGIN_MAX_FAILURES` failures inside the last `LOGIN_LOCK_MINUTES` (counting only failures since its last success), `POST /auth/login` returns **429** for that account, even with the right password.
- A wrong ID and a wrong password return the same 401 message, and the API runs a password hash check for unknown IDs too, so response time does not reveal which employee IDs exist.

## Known limits (honest notes for the defense)

- Wrong attempts for an ID that does not exist cannot be counted per account, because the audit log needs a user row. A per-IP rate limit is planned for 5B.
- Tokens cannot be revoked before they expire. Signing out only forgets the token in the browser. A short expiry limits the risk. A token blocklist would be the next step.
- The Streamlit session keeps the token in server memory. Refreshing the browser tab starts a new session, so the user signs in again.
- The reset request needs a signed-in session, so it covers "I want a new password" but not "I cannot sign in at all". A public "Forgot password" page, tied to a real mailbox, would be the next step.
- Traffic is plain HTTP on localhost. A real deployment would put HTTPS in front.
