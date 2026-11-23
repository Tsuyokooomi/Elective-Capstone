"""A fake email service for the demo.

Real deployments would hand the message to SMTP or an n8n workflow. Here the message goes into an
in-memory outbox (admins can read it at GET /mock/outbox and on the dashboard) and is also
printed to the API log, so a demo works without a mail server. The outbox is lost on restart."""
from collections import deque
from datetime import datetime, timezone

OUTBOX: deque = deque(maxlen=20)


def send_reset_email(to: str, link: str, minutes: int) -> dict:
    mail = {
        "to": to,
        "subject": "Reset your CapstoneCompany password",
        "link": link,
        "body": (f"Hello,\n\nUse this link to choose a new password. It works once and expires in "
                 f"{minutes} minutes:\n{link}\n\nIf you did not ask for this, ignore this email."),
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }
    OUTBOX.appendleft(mail)
    print(f"[mock email] to {to}: {link}", flush=True)
    return mail
