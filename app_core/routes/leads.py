import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from app_core.database import repository
from app_core.models import (
    AnalyticsSummary,
    LeadIn,
    LeadRecord,
    LeadStatusUpdate,
    ProcessLeadResponse,
)
from app_core.services.processor import process_lead_pipeline

logger = logging.getLogger("speed-to-lead.leads")
router = APIRouter(prefix="/api", tags=["Leads & Analytics"])

# Four distinct people and companies representing the Blaze AI CFO target spectrum
SAMPLE_PRESETS = [
    {
        "id": "185_multifamily",
        "title": "Sarah Jenkins — Peakline Living (185 doors)",
        "hint": "185 doors · late rent & manual bookkeeping pain · wants demo",
        "lead": {
            "name": "Sarah Jenkins",
            "email": "sarah@peaklineliving.com",
            "phone": "+1-555-014-2201",
            "company": "Peakline Living",
            "doors": 185,
            "message": "We manage 185 doors across Austin and late rent collection is killing our cash flow, plus my staff spends 20 hours a week on manual bookkeeping. Can we schedule a demo this week?"
        }
    },
    {
        "id": "45_growth",
        "title": "David Morales — Horizon Property Partners (45 doors)",
        "hint": "45 doors · needs faster vendor invoicing & payments",
        "lead": {
            "name": "David Morales",
            "email": "david@horizonprops.com",
            "phone": "+1-555-018-9923",
            "company": "Horizon Property Partners",
            "doors": 45,
            "message": "We currently manage 45 doors and are growing fast. Our biggest bottleneck is invoicing vendors faster and tracking payments across our maintenance contractors."
        }
    },
    {
        "id": "12_boutique",
        "title": "Chloe Dupont — Atelier Stays (12 doors)",
        "hint": "12 doors · boutique luxury rentals · pricing inquiry",
        "lead": {
            "name": "Chloe Dupont",
            "email": "chloe@atelierstays.com",
            "phone": "+1-555-017-3341",
            "company": "Atelier Stays",
            "doors": 12,
            "message": "We operate 12 boutique rental doors downtown. Can you tell us about your pricing tiers and if you support small portfolios?"
        }
    },
    {
        "id": "1_renter",
        "title": "Tyler Vance — Individual Tenant (1 door)",
        "hint": "1 door · tenant inquiry · looking to pay own rent",
        "lead": {
            "name": "Tyler Vance",
            "email": "tyler.vance92@gmail.com",
            "phone": "+1-555-019-8812",
            "company": "Private Tenant",
            "doors": 1,
            "message": "Hi, I live in Unit 4B at Elm Street and was wondering how I can pay my rent to my landlord using your app?"
        }
    }
]


@router.get("/presets")
async def get_presets():
    """Returns curated preset leads for the web dashboard."""
    return SAMPLE_PRESETS


@router.get("/leads", response_model=List[LeadRecord])
async def list_leads(
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None),
):
    """Retrieves all qualified and incoming leads."""
    return await repository.list_leads(limit=limit, status=status)


@router.get("/leads/{lead_id}", response_model=LeadRecord)
async def get_lead(lead_id: str):
    """Retrieves a single lead by its identifier."""
    lead = await repository.get_lead(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.patch("/leads/{lead_id}/status")
async def update_lead_status(lead_id: str, payload: LeadStatusUpdate):
    """Updates lead pipeline status."""
    success = await repository.update_status(lead_id, payload.status)
    if not success:
        raise HTTPException(status_code=404, detail="Lead not found or update failed")
    return {"status": "updated", "lead_id": lead_id, "new_status": payload.status}


@router.get("/analytics", response_model=AnalyticsSummary)
async def get_analytics():
    """Returns speed-to-lead benchmark metrics."""
    return await repository.get_analytics()


@router.post("/leads/simulate", response_model=ProcessLeadResponse)
async def simulate_lead(lead: LeadIn):
    """Direct simulator endpoint for the web dashboard test runner."""
    return await process_lead_pipeline(lead, source="web_dashboard_simulator")


@router.post("/admin/reset")
async def reset_demo_data():
    """Clears all leads from database for demo reset."""
    cleared_count = await repository.reset_leads()
    return {"status": "cleared", "leads_deleted": cleared_count}
