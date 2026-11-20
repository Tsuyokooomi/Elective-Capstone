import logging
from datetime import datetime, timezone

import httpx

from app.config import settings

logger = logging.getLogger("aihas.webhook")


def send_webhook(event: str, data: dict, url: str | None = None, post=None) -> bool:
    """Send an event to the configured webhook (for example n8n). Never raises:
    a broken webhook must not break the chat."""
    url = settings.webhook_url if url is None else url
    if not url:
        return False
    post = post or httpx.post
    body = {"event": event, "sent_at": datetime.now(timezone.utc).isoformat(), "data": data}
    try:
        response = post(url, json=body, timeout=3.0)
        return response.status_code < 400
    except Exception:
        logger.warning("webhook %s failed", event, exc_info=True)
        return False
