import pytest
from httpx import ASGITransport, AsyncClient

from app import app


@pytest.mark.asyncio
async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "storage" in data
        assert "ai" in data


@pytest.mark.asyncio
async def test_meta_webhook_challenge_verification():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Successful challenge verification
        resp = await client.get(
            "/webhooks/facebook-lead",
            params={
                "hub.mode": "subscribe",
                "hub.challenge": "11582012",
                "hub.verify_token": "speed-to-lead-token",
            },
        )
        assert resp.status_code == 200
        assert resp.text == "11582012"

        # Invalid token
        resp_bad = await client.get(
            "/webhooks/facebook-lead",
            params={
                "hub.mode": "subscribe",
                "hub.challenge": "11582012",
                "hub.verify_token": "wrong-token",
            },
        )
        assert resp_bad.status_code == 403


@pytest.mark.asyncio
async def test_lead_pipeline_sub_60s():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        sample_lead = {
            "name": "Jordan Lee",
            "email": "jordan@northstarproperties.com",
            "phone": "+1-555-010-2040",
            "company": "Northstar Property Group",
            "doors": 185,
            "message": "We manage 185 doors across our multifamily portfolio and need automated intake and first responses.",
        }

        resp = await client.post("/api/leads/simulate", json=sample_lead)
        assert resp.status_code == 200
        data = resp.json()

        # Step 1: Returned qualification with fit score 1-5
        assert data["status"] == "processed"
        assert "lead_id" in data
        assert 1 <= data["qualification"]["fit_score"] <= 5
        assert len(data["qualification"]["reason"]) > 0
        assert len(data["qualification"]["suggested_reply"]) > 0

        # Step 4: Speed SLA verification (<60s)
        assert data["under_60_seconds"] is True
        assert data["processing_ms"] < 60000


@pytest.mark.asyncio
async def test_analytics_and_leads_listing():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Check leads listing
        resp_leads = await client.get("/api/leads")
        assert resp_leads.status_code == 200
        leads = resp_leads.json()
        assert isinstance(leads, list)

        # Check analytics
        resp_analytics = await client.get("/api/analytics")
        assert resp_analytics.status_code == 200
        analytics = resp_analytics.json()
        assert "total_leads" in analytics
        assert "avg_processing_ms" in analytics
        assert "sla_percentage" in analytics
