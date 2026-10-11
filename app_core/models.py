from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LeadIn(BaseModel):
    """Input payload for lead creation or webhook simulation."""
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=160, description="Full name of the lead")
    email: EmailStr = Field(..., description="Contact email address")
    phone: str = Field(..., min_length=5, max_length=40, description="Phone number")
    company: str = Field(..., min_length=1, max_length=200, description="Company or organization name")
    doors: int = Field(..., ge=0, le=1_000_000, description="Number of doors/units managed")
    message: str = Field(..., min_length=1, max_length=5000, description="Inquiry or message text")


class Qualification(BaseModel):
    """LLM or rule-engine qualification outcome."""
    fit_score: int = Field(..., ge=1, le=5, description="Fit score from 1 (poor) to 5 (excellent)")
    reason: str = Field(..., min_length=1, max_length=500, description="One-sentence rationalization")
    intent: Literal["low", "medium", "high"] = Field(..., description="Perceived buying/evaluation intent")
    suggested_reply: str = Field(..., min_length=1, max_length=1500, description="Personalized draft first response")


class LeadRecord(BaseModel):
    """Complete lead data model as stored in the database."""
    id: str
    created_at: str
    name: str
    email: str
    phone: str
    company: str
    doors: int
    message: str
    fit_score: Optional[int] = None
    reason: Optional[str] = None
    intent: Optional[str] = None
    suggested_reply: Optional[str] = None
    status: Literal["received", "qualified", "contacted", "converted", "disqualified", "failed"] = "received"
    processing_ms: Optional[int] = None
    end_to_end_seconds: Optional[float] = None
    delivery_channel: Optional[str] = "INTERNAL_DASHBOARD"
    delivery_failed: bool = False
    scored_by: str = "llm"  # "llm" or "heuristic_fallback"
    source: str = "facebook_lead_ad_simulation"
    slack_sent: bool = False
    raw_payload: Optional[Dict[str, Any]] = None


class LeadStatusUpdate(BaseModel):
    """Payload for updating lead pipeline status."""
    status: Literal["received", "qualified", "contacted", "converted", "disqualified"]


class ProcessLeadResponse(BaseModel):
    """Standardized response when a lead is ingested and processed."""
    status: str
    lead_id: str
    qualification: Qualification
    processing_ms: int
    end_to_end_seconds: float
    target_seconds: int
    under_60_seconds: bool
    delivery_channel: str
    delivery_failed: bool = False
    scored_by: str = "llm"
    deduplicated: bool = False
    storage_engine: str  # "supabase" or "local_sqlite"


class AnalyticsSummary(BaseModel):
    """Aggregate speed-to-lead and qualification KPIs."""
    total_leads: int
    qualified_leads: int
    avg_processing_ms: float
    under_60_count: int
    sla_percentage: float
    intent_distribution: Dict[str, int]
    score_distribution: Dict[int, int]
    storage_engine: str
