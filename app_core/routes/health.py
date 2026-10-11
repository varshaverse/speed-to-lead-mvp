import time
from fastapi import APIRouter
from app_core.config import settings
from app_core.database import repository

router = APIRouter(tags=["Health"])
start_time = time.time()


@router.get("/health")
def health_check():
    """System health check and integration availability."""
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - start_time),
        "target_sla_seconds": settings.TARGET_SLA_SECONDS,
        "storage": {
            "engine": repository.storage_engine,
            "supabase_configured": settings.is_supabase_configured,
            "local_sqlite_fallback_active": not settings.is_supabase_configured,
        },
        "ai": {
            "provider": "openai" if settings.is_openai_configured else "heuristic_simulator",
            "model": settings.OPENAI_MODEL if settings.is_openai_configured else "heuristic_fallback",
            "openai_configured": settings.is_openai_configured,
        },
        "notifications": {
            "discord_configured": settings.is_discord_configured,
            "slack_configured": settings.is_slack_configured,
            "sms_configured": settings.is_sms_configured,
            "email_configured": settings.is_email_configured,
            "active_primary_channel": "DISCORD" if settings.is_discord_configured else ("SLACK" if settings.is_slack_configured else "INTERNAL_DASHBOARD"),
        },
        "security": {
            "webhook_secret_required": bool(settings.WEBHOOK_SECRET),
            "meta_signature_verification": bool(settings.FB_APP_SECRET),
        },
    }
