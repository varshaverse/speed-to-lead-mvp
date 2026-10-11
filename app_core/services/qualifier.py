import asyncio
import json
import logging
from pathlib import Path
from typing import Tuple

from openai import AsyncOpenAI

from app_core.config import settings
from app_core.models import LeadIn, Qualification

logger = logging.getLogger("speed-to-lead.qualifier")

PROMPT_FILE = Path(__file__).resolve().parent.parent.parent / "prompts" / "qualify.txt"


def load_system_prompt() -> str:
    """Loads system prompt from prompts/qualify.txt or provides fallback."""
    if PROMPT_FILE.exists():
        try:
            return PROMPT_FILE.read_text(encoding="utf-8").strip()
        except Exception as exc:
            logger.warning("Could not read %s: %s", PROMPT_FILE, exc)
    return (
        "You are Blaze, an AI CFO for property managers with 50-500 doors. "
        "Score fit from 1 to 5. 1 = tenant/1 unit, 2 = under 10 doors, 3 = 10-49 doors, "
        "4 = 50-199 doors with clear need, 5 = 50-500 doors with explicit pain (late rent, bookkeeping, "
        "invoicing, cash flow) and demo intent. Return JSON with fit_score, reason, intent, suggested_reply."
    )


def heuristic_qualify(lead: LeadIn) -> Qualification:
    """Heuristic fallback qualifier aligned with Blaze AI CFO 50-500 door scoring rules."""
    doors = lead.doors
    msg_lower = lead.message.lower()

    # Pain points specific to Blaze AI CFO
    pain_keywords = ["late rent", "bookkeeping", "invoicing", "invoice", "cash flow", "collections", "accounting"]
    demo_keywords = ["demo", "schedule", "meet", "intro", "call", "this week", "asap"]

    has_pain = any(k in msg_lower for k in pain_keywords)
    has_demo = any(k in msg_lower for k in demo_keywords)

    first_name = lead.name.strip().split()[0] if lead.name.strip() else "there"

    # Blaze AI CFO Scoring Guide:
    # 1 = tenant or 1-unit owner
    if doors <= 1:
        fit_score = 1
        intent = "low"
        reason = f"Lead manages only {doors} unit and is outside Blaze's 50-500 B2B commercial threshold."
        suggested_reply = (
            f"Hi {first_name}, thanks for reaching out. Blaze is built specifically for commercial property managers "
            f"managing 50+ doors, so our automated CFO platform won't be a fit for single-unit needs."
        )
    # 2 = under 10 doors
    elif doors < 10:
        fit_score = 2
        intent = "low"
        reason = f"Portfolio size ({doors} doors) is below Blaze's minimum threshold of 50 doors."
        suggested_reply = (
            f"Hi {first_name}, thank you for contacting Blaze. While we typically serve growing property managers with "
            f"50+ doors, we'd be glad to share self-serve resources that help smaller portfolios."
        )
    # 3 = 10-49 doors
    elif 10 <= doors <= 49 and not (has_pain and has_demo):
        fit_score = 3
        intent = "medium" if has_demo else "low"
        reason = f"Emerging manager with {doors} doors inquiring about solution fit before reaching enterprise scale."
        suggested_reply = (
            f"Hi {first_name}, thanks for reaching out to Blaze! Managing {doors} doors is a pivotal transition point for cash flow automation. "
            f"What accounting workflow currently consumes most of your team's time?"
        )
    # 4 = 50-199 doors with clear need (or 45 doors scaling)
    elif (50 <= doors <= 199 and not (has_pain and has_demo)) or (35 <= doors <= 49 and has_pain):
        fit_score = 4
        intent = "medium"
        reason = f"Ideal portfolio scale ({doors} doors) with operational need for financial automation."
        suggested_reply = (
            f"Hi {first_name}, thanks for reaching out! With {doors} doors under management, automating invoices and owner financials with Blaze can save hours each week. "
            f"Would you be open to a quick 15-minute walkthrough of our CFO workflows?"
        )
    # 5 = 50-500 doors with explicit financial pain and demo intent
    else:
        fit_score = 5
        intent = "high"
        reason = f"Perfect target fit ({doors} doors) experiencing explicit financial bottlenecks and requesting an immediate demo."
        suggested_reply = (
            f"Hi {first_name}, thanks for reaching out! With {doors} doors, bottlenecks in bookkeeping and rent collection directly impact bottom-line margins. "
            f"I would love to give you a demo of Blaze this week—does tomorrow afternoon work for a quick call?"
        )

    return Qualification(
        fit_score=fit_score,
        reason=reason,
        intent=intent,
        suggested_reply=suggested_reply,
    )


async def qualify_lead(lead: LeadIn) -> Tuple[Qualification, str]:
    """Qualifies a lead using OpenAI Structured Outputs with 10s timeout and graceful fallback.

    Returns:
        (Qualification, scored_by)
    """
    if not settings.is_openai_configured:
        logger.info("OPENAI_API_KEY not configured. Using heuristic scorer (scored_by: heuristic_fallback).")
        return heuristic_qualify(lead), "heuristic_fallback"

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=10.0)
    system_prompt = load_system_prompt()
    payload = lead.model_dump(mode="json")

    try:
        completion = await asyncio.wait_for(
            client.beta.chat.completions.parse(
                model=settings.OPENAI_MODEL,
                temperature=0.2,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            "Qualify this inbound lead according to schema:\n"
                            + json.dumps(payload, ensure_ascii=False)
                        ),
                    },
                ],
                response_format=Qualification,
            ),
            timeout=10.0,
        )

        parsed: Qualification = completion.choices[0].message.parsed
        if parsed:
            return parsed, "llm"
        raise ValueError("OpenAI returned empty structured output")

    except asyncio.TimeoutError:
        logger.error("OpenAI qualification timed out after 10s. Falling back to heuristic scorer.")
        return heuristic_qualify(lead), "heuristic_fallback"
    except Exception as exc:
        logger.error("OpenAI qualification failed (%s: %s). Falling back to heuristic scorer.", type(exc).__name__, exc)
        return heuristic_qualify(lead), "heuristic_fallback"
