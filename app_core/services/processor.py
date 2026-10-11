import logging
import time
from app_core.config import settings
from app_core.database import repository
from app_core.models import LeadIn, ProcessLeadResponse, Qualification
from app_core.services.notifier import notify_channels
from app_core.services.qualifier import qualify_lead
from app_core.services.sheets import sync_lead_to_sheet

logger = logging.getLogger("speed-to-lead.processor")


def _lead_to_dict(lead: LeadIn) -> dict:
    """Plain dict of the incoming lead, whichever pydantic version is installed."""
    if hasattr(lead, "model_dump"):
        return lead.model_dump()
    if hasattr(lead, "dict"):
        return lead.dict()
    return dict(vars(lead))


async def process_lead_pipeline(
    lead: LeadIn,
    source: str = "facebook_lead_ad_simulation",
) -> ProcessLeadResponse:
    """Executes the high-speed lead qualification pipeline with deduplication and exact timer measurement."""
    # Step 0: Check for duplicate lead within 5 minutes
    existing = await repository.find_recent_duplicate(lead.email, lead.message, window_minutes=5)
    if existing and existing.fit_score is not None:
        logger.info("Deduplication match: returning existing lead id=%s for %s", existing.id, lead.email)
        return ProcessLeadResponse(
            status="processed",
            lead_id=existing.id,
            qualification=Qualification(
                fit_score=existing.fit_score,
                reason=existing.reason or "Existing lead qualification reused",
                intent=existing.intent or "medium",  # type: ignore
                suggested_reply=existing.suggested_reply or "",
            ),
            processing_ms=existing.processing_ms or 10,
            end_to_end_seconds=existing.end_to_end_seconds or 0.1,
            target_seconds=settings.TARGET_SLA_SECONDS,
            under_60_seconds=True,
            delivery_channel=existing.delivery_channel or "INTERNAL_DASHBOARD",
            delivery_failed=existing.delivery_failed,
            scored_by=existing.scored_by,
            deduplicated=True,
            storage_engine=repository.storage_engine,
        )

    # Start latency timer exactly when webhook request is received
    started = time.perf_counter()

    # Step 1: Staged persistence - persist raw incoming lead immediately
    lead_id = await repository.save_raw_lead(lead, source=source)
    logger.info("Ingested and staged raw lead id=%s from company=%s", lead_id, lead.company)

    try:
        # Step 2: AI Qualification (10s timeout, graceful fallback to heuristic)
        qualification, scored_by = await qualify_lead(lead)

        # Step 3 & 4: Stop timer AFTER the notification send returns
        pre_dispatch_ms = int((time.perf_counter() - started) * 1000)
        delivered, channel_name, delivery_failed = await notify_channels(
            lead, qualification, lead_id, pre_dispatch_ms / 1000.0
        )

        # Stop latency timer: Total end-to-end seconds from receipt to send completion
        total_elapsed_ms = int((time.perf_counter() - started) * 1000)
        end_to_end_sec = round(total_elapsed_ms / 1000.0, 2)
        under_sla = end_to_end_sec < float(settings.TARGET_SLA_SECONDS)

        # Step 5: Update lead in database with completed qualification and exact delivery latency
        await repository.update_lead_qualification(
            lead_id=lead_id,
            qualification=qualification,
            elapsed_ms=total_elapsed_ms,
            end_to_end_seconds=end_to_end_sec,
            delivery_channel=channel_name,
            delivery_failed=delivery_failed,
            scored_by=scored_by,
            slack_sent=(channel_name in ["SLACK", "DISCORD"] and not delivery_failed),
        )

        logger.info(
            "Delivered lead id=%s score=%d time=%.2fs (%dms) SLA=%s channel=%s scored_by=%s",
            lead_id,
            qualification.fit_score,
            end_to_end_sec,
            total_elapsed_ms,
            under_sla,
            channel_name,
            scored_by,
        )

        # Step 6: Sync to Google Sheet. Runs AFTER delivery, in a background thread,
        # so it adds no latency to the notification. Never allowed to break the pipeline.
        try:
            sheet_row = _lead_to_dict(lead)
            sheet_row.update(
                {
                    "fit_score": qualification.fit_score,
                    "reason": qualification.reason,
                    "intent": qualification.intent,
                    "suggested_reply": qualification.suggested_reply,
                    "end_to_end_seconds": end_to_end_sec,
                    "delivery_channel": channel_name,
                }
            )
            sync_lead_to_sheet(sheet_row)
        except Exception as sheet_exc:
            logger.error("Sheet sync setup failed for lead_id=%s: %s", lead_id, sheet_exc)

        return ProcessLeadResponse(
            status="processed",
            lead_id=lead_id,
            qualification=qualification,
            processing_ms=total_elapsed_ms,
            end_to_end_seconds=end_to_end_sec,
            target_seconds=settings.TARGET_SLA_SECONDS,
            under_60_seconds=under_sla,
            delivery_channel=channel_name,
            delivery_failed=delivery_failed,
            scored_by=scored_by,
            deduplicated=False,
            storage_engine=repository.storage_engine,
        )

    except Exception as exc:
        elapsed_fail_ms = int((time.perf_counter() - started) * 1000)
        logger.exception("Pipeline failed for lead_id=%s: %s", lead_id, exc)
        await repository.mark_lead_failed(lead_id, str(exc), elapsed_fail_ms)
        raise