import pytest
from httpx import ASGITransport, AsyncClient

from app import app
from app_core.models import LeadIn
from app_core.services.qualifier import heuristic_qualify, qualify_lead


@pytest.mark.asyncio
async def test_scorer_returns_valid_structured_output():
    """Verifies that the qualification scorer returns fit_score (1-5), single-sentence reason, intent, and reply."""
    lead = LeadIn(
        name="Sarah Jenkins",
        email="sarah@peakline.com",
        phone="+1-555-014-2201",
        company="Peakline Living",
        doors=185,
        message="Managing 185 doors in Austin. Late rent collection and manual bookkeeping are hurting us. Need a demo this week.",
    )
    qual, scored_by = await qualify_lead(lead)
    assert 1 <= qual.fit_score <= 5
    assert len(qual.reason) > 5
    # Reason should be exactly one sentence (one period or ending punct)
    assert qual.intent in ["low", "medium", "high"]
    assert len(qual.suggested_reply) > 10
    assert scored_by in ["llm", "heuristic_fallback"]


@pytest.mark.asyncio
async def test_fallback_works_when_llm_errors():
    """Verifies heuristic scorer fallback works reliably when OpenAI is unavailable."""
    # Test 185 doors with pain -> expect fit 5
    lead_5 = LeadIn(
        name="Sarah Jenkins",
        email="sarah@peakline.com",
        phone="+15550142201",
        company="Peakline Living",
        doors=185,
        message="185 doors. Late rent and bookkeeping pain. Need a demo this week.",
    )
    qual_5 = heuristic_qualify(lead_5)
    assert qual_5.fit_score == 5
    assert qual_5.intent == "high"

    # Test 1 door renter -> expect fit 1
    lead_1 = LeadIn(
        name="Tyler Vance",
        email="tyler@gmail.com",
        phone="+15550198812",
        company="Private Tenant",
        doors=1,
        message="How can I pay my rent to my landlord using your app?",
    )
    qual_1 = heuristic_qualify(lead_1)
    assert qual_1.fit_score == 1
    assert qual_1.intent == "low"


@pytest.mark.asyncio
async def test_deduplication_works_within_5_minutes():
    """Verifies deduplication on (email + message) within 5 minutes returns existing lead."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # First: reset database
        await client.post("/api/admin/reset")

        lead_payload = {
            "name": "David Morales",
            "email": "david@horizonprops.com",
            "phone": "+1-555-018-9923",
            "company": "Horizon Property Partners",
            "doors": 45,
            "message": "We manage 45 doors and need faster vendor invoicing.",
        }

        # First ingestion
        res1 = await client.post("/api/leads/simulate", json=lead_payload)
        assert res1.status_code == 200
        d1 = res1.json()
        lead_id_1 = d1["lead_id"]
        assert d1["deduplicated"] is False

        # Duplicate ingestion within 5 minutes
        res2 = await client.post("/api/leads/simulate", json=lead_payload)
        assert res2.status_code == 200
        d2 = res2.json()
        assert d2["deduplicated"] is True
        assert d2["lead_id"] == lead_id_1  # Reuses existing lead


@pytest.mark.asyncio
async def test_latency_is_stored_in_seconds():
    """Verifies end_to_end_seconds is measured, stored, and returned in the API."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        lead_payload = {
            "name": "Chloe Dupont",
            "email": "chloe@atelierstays.com",
            "phone": "+1-555-017-3341",
            "company": "Atelier Stays",
            "doors": 12,
            "message": "We operate 12 boutique rental doors. What are your pricing tiers?",
        }
        res = await client.post("/api/leads/simulate", json=lead_payload)
        assert res.status_code == 200
        data = res.json()
        assert "end_to_end_seconds" in data
        assert isinstance(data["end_to_end_seconds"], (int, float))
        assert data["end_to_end_seconds"] < 60.0
        assert "delivery_channel" in data
