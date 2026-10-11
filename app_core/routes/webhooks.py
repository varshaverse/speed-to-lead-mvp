import hashlib
import hmac
import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import ValidationError

from app_core.config import settings
from app_core.models import LeadIn, ProcessLeadResponse
from app_core.services.processor import process_lead_pipeline

logger = logging.getLogger("speed-to-lead.webhooks")
router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.get("/facebook-lead")
async def verify_facebook_webhook(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
):
    """Handles the Meta/Facebook Webhook Verification Challenge.

    When you configure a webhook in Meta App Dashboard, Facebook sends a GET request
    with hub.mode, hub.verify_token, and hub.challenge.
    """
    allowed_tokens = {
        tok for tok in [
            settings.FB_VERIFY_TOKEN,
            settings.WEBHOOK_SECRET,
            "speed-to-lead-token",
        ] if tok
    }
    if hub_mode == "subscribe" and hub_verify_token in allowed_tokens:
        logger.info("Facebook webhook verification challenge successful.")
        return Response(content=hub_challenge or "", media_type="text/plain")

    logger.warning("Facebook webhook verification challenge failed: token mismatch.")
    raise HTTPException(status_code=403, detail="Verification token mismatch")


def _verify_meta_signature(raw_body: bytes, signature_header: Optional[str]) -> bool:
    """Validates X-Hub-Signature-256 header using FB_APP_SECRET."""
    if not settings.FB_APP_SECRET:
        return True  # Signature check optional if app secret not configured
    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected_sig = hmac.new(
        key=settings.FB_APP_SECRET.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    provided_sig = signature_header.replace("sha256=", "").strip()
    return hmac.compare_digest(expected_sig, provided_sig)


@router.post("/facebook-lead", response_model=ProcessLeadResponse)
async def receive_facebook_lead(request: Request):
    """Receives and qualifies incoming Facebook Lead Ad webhooks.

    Accepts both:
    1. Direct normalized JSON payloads (`{"name": "...", "email": "...", ...}`)
    2. Simulated or raw Meta Leadgen event format
    """
    raw_body = await request.body()

    # 1. Check shared secret header if WEBHOOK_SECRET is active
    if settings.WEBHOOK_SECRET:
        supplied_secret = request.headers.get("x-webhook-secret", "")
        if supplied_secret != settings.WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail="Invalid X-Webhook-Secret")

    # 2. Check Meta HMAC signature if X-Hub-Signature-256 is present
    sig_header = request.headers.get("x-hub-signature-256")
    if sig_header and not _verify_meta_signature(raw_body, sig_header):
        raise HTTPException(status_code=401, detail="Invalid X-Hub-Signature-256 signature")

    # 3. Parse JSON body
    try:
        data: Dict[str, Any] = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    # 4. Handle Meta Leadgen payload structure vs direct LeadIn structure
    lead_input: LeadIn
    source = "facebook_lead_ad_direct"

    if "entry" in data and isinstance(data["entry"], list):
        # Meta Leadgen Webhook format
        source = "facebook_leadgen_event"
        try:
            entry = data["entry"][0]
            change = entry.get("changes", [{}])[0]
            val = change.get("value", {})
            lead_input = LeadIn(
                name=val.get("name", "Meta Lead"),
                email=val.get("email", "lead@meta-ad.com"),
                phone=val.get("phone", "+15550001111"),
                company=val.get("company", "Meta Advertiser"),
                doors=int(val.get("doors", 10)),
                message=val.get("message", "Inquiry from Facebook Lead Ad"),
            )
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Could not parse Meta payload: {exc}") from exc
    else:
        try:
            lead_input = LeadIn.model_validate(data)
        except ValidationError as val_err:
            raise HTTPException(status_code=422, detail=val_err.errors()) from val_err

    # 5. Process through the qualification pipeline
    try:
        response = await process_lead_pipeline(lead_input, source=source)
        return response
    except Exception as exc:
        logger.exception("Lead processing failed")
        raise HTTPException(
            status_code=502,
            detail="Lead processing failed. Check logs and provider configuration.",
        ) from exc
