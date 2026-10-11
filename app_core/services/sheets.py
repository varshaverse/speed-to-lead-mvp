import os
import logging
import threading
import requests

logger = logging.getLogger(__name__)

# Each sheet column, with alternate field names your lead might use
ALIASES = {
    "name": ["name", "full_name"],
    "email": ["email"],
    "phone": ["phone"],
    "company": ["company", "company_name"],
    "doors": ["doors", "doors_managed", "units", "num_doors"],
    "message": ["message", "inquiry"],
    "fit_score": ["fit_score", "score"],
    "reason": ["reason"],
    "intent": ["intent"],
    "suggested_reply": ["suggested_reply", "reply", "draft_reply"],
    "end_to_end_seconds": ["end_to_end_seconds"],
    "delivery_channel": ["delivery_channel", "channel"],
}


def _get(lead, names):
    for n in names:
        v = lead.get(n) if isinstance(lead, dict) else getattr(lead, n, None)
        if v is not None:
            return v
    return ""


def _post(url, payload):
    try:
        r = requests.post(url, json=payload, timeout=10, allow_redirects=True)
        if not (r.ok and r.text.strip() == "ok"):
            logger.error("Sheet sync rejected: status=%s body=%s", r.status_code, r.text[:200])
        else:
            logger.info("Sheet sync ok")
    except Exception as exc:
        logger.error("Sheet sync failed: %s", exc)


def sync_lead_to_sheet(lead) -> None:
    """Fire-and-forget, so it never slows the Discord message."""
    url = os.getenv("SHEET_WEBHOOK_URL")
    if not url:
        return
    payload = {key: _get(lead, names) for key, names in ALIASES.items()}
    payload["secret"] = os.getenv("SHEET_SECRET", "")
    threading.Thread(target=_post, args=(url, payload), daemon=True).start()