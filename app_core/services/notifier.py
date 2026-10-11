import logging
from typing import Optional, Tuple

import httpx

from app_core.config import settings
from app_core.models import LeadIn, Qualification

logger = logging.getLogger("speed-to-lead.notifier")


async def notify_discord(
    lead: LeadIn,
    qualification: Qualification,
    lead_id: Optional[str],
    end_to_end_seconds: float,
) -> bool:
    """Dispatches a rich Discord embed notification (Primary Channel)."""
    if not settings.is_discord_configured:
        return False

    color = 0x10B981 if qualification.fit_score >= 4 else (0xF59E0B if qualification.fit_score == 3 else 0xEF4444)
    embed = {
        "title": f"⚡ Blaze AI CFO Lead Alert: {lead.company} (Fit {qualification.fit_score}/5)",
        "description": f"**Lead Name:** {lead.name}\n**Company:** {lead.company}\n**Doors:** {lead.doors:,} units\n**Phone:** {lead.phone}\n**Email:** {lead.email}",
        "color": color,
        "fields": [
            {"name": "Fit Score", "value": f"**{qualification.fit_score}/5** ({qualification.intent.upper()} INTENT)", "inline": True},
            {"name": "Speed-to-Lead SLA", "value": f"⚡ **{end_to_end_seconds:.1f}s end-to-end**", "inline": True},
            {"name": "AI Qualification Rationale", "value": qualification.reason, "inline": False},
            {"name": "Drafted First Reply", "value": f"```{qualification.suggested_reply}```", "inline": False},
        ],
        "footer": {"text": f"Lead ID: {lead_id or 'local'} | Sub-60s Inbound Response"},
    }

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.post(settings.DISCORD_WEBHOOK_URL, json={"embeds": [embed]})
            resp.raise_for_status()
            logger.info("Discord notification delivered for lead %s in %.2fs", lead_id, end_to_end_seconds)
            return True
    except Exception as exc:
        logger.error("Discord notification delivery failed (%s: %s)", type(exc).__name__, exc)
        return False


async def notify_slack(
    lead: LeadIn,
    qualification: Qualification,
    lead_id: Optional[str],
    end_to_end_seconds: float,
) -> bool:
    """Dispatches formatted Slack Block Kit alert if SLACK_WEBHOOK_URL is set."""
    if not settings.is_slack_configured:
        return False

    score_emojis = {5: "🔥", 4: "⭐", 3: "👀", 2: "⚠️", 1: "🛑"}
    score_emoji = score_emojis.get(qualification.fit_score, "📋")
    under_target = end_to_end_seconds < settings.TARGET_SLA_SECONDS
    sla_badge = "⚡ UNDER 60s" if under_target else "⏱️ OVER SLA"

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{score_emoji} Blaze AI CFO Alert: {lead.company} (Score {qualification.fit_score}/5)",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Contact:*\n{lead.name}"},
                {"type": "mrkdwn", "text": f"*Doors:*\n{lead.doors:,} units"},
                {"type": "mrkdwn", "text": f"*Intent:*\n{qualification.intent.upper()}"},
                {"type": "mrkdwn", "text": f"*Latency:*\n{end_to_end_seconds:.1f}s ({sla_badge})"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*AI Assessment:*\n_{qualification.reason}_"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Drafted Reply:*\n>{qualification.suggested_reply}"},
        },
    ]

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.post(
                settings.SLACK_WEBHOOK_URL,
                json={"text": f"New Lead Alert: {lead.name} from {lead.company}", "blocks": blocks},
            )
            resp.raise_for_status()
            logger.info("Slack notification delivered for lead %s in %.2fs", lead_id, end_to_end_seconds)
            return True
    except Exception as exc:
        logger.error("Slack notification delivery failed (%s: %s)", type(exc).__name__, exc)
        return False


async def notify_channels(
    lead: LeadIn,
    qualification: Qualification,
    lead_id: Optional[str],
    end_to_end_seconds: float,
) -> Tuple[bool, str, bool]:
    """Dispatches alerts to configured channels with Discord as primary.

    Returns:
        (delivered: bool, channel_name: str, delivery_failed: bool)
    """
    has_external_config = (
        settings.is_discord_configured
        or settings.is_slack_configured
        or settings.is_sms_configured
        or settings.is_email_configured
    )

    # 1. Primary: Discord
    if settings.is_discord_configured:
        sent = await notify_discord(lead, qualification, lead_id, end_to_end_seconds)
        if sent:
            return True, "DISCORD", False
        else:
            logger.error("Primary channel DISCORD failed. Falling back to INTERNAL_DASHBOARD with delivery_failed flag.")
            return False, "INTERNAL_DASHBOARD", True

    # 2. Slack (if configured and Discord not set)
    if settings.is_slack_configured:
        sent = await notify_slack(lead, qualification, lead_id, end_to_end_seconds)
        if sent:
            return True, "SLACK", False
        else:
            logger.error("SLACK dispatch failed. Falling back to INTERNAL_DASHBOARD with delivery_failed flag.")
            return False, "INTERNAL_DASHBOARD", True

    # 3. No external channels configured
    return True, "INTERNAL_DASHBOARD", False
