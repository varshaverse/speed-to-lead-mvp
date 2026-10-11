import asyncio
import hashlib
import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from app_core.config import settings
from app_core.models import AnalyticsSummary, LeadIn, LeadRecord, Qualification

logger = logging.getLogger("speed-to-lead.database")

supabase_client = None
if settings.is_supabase_configured:
    try:
        from supabase import create_client
        supabase_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
        logger.info("Supabase client initialized successfully.")
    except Exception as exc:
        logger.warning("Could not initialize Supabase client: %s. Falling back to SQLite.", exc)


def _init_sqlite_db():
    """Initializes local SQLite database with required columns and indexes."""
    conn = sqlite3.connect(settings.SQLITE_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT NOT NULL,
            company TEXT NOT NULL,
            doors INTEGER NOT NULL,
            message TEXT NOT NULL,
            dedupe_hash TEXT,
            fit_score INTEGER,
            reason TEXT,
            intent TEXT,
            suggested_reply TEXT,
            status TEXT NOT NULL DEFAULT 'received',
            processing_ms INTEGER,
            end_to_end_seconds REAL,
            delivery_channel TEXT DEFAULT 'INTERNAL_DASHBOARD',
            delivery_failed INTEGER NOT NULL DEFAULT 0,
            scored_by TEXT DEFAULT 'llm',
            source TEXT NOT NULL DEFAULT 'facebook_lead_ad_simulation',
            slack_sent INTEGER NOT NULL DEFAULT 0,
            raw_payload TEXT
        )
    """)
    # Safe column additions if table already existed
    for col, col_type in [
        ("dedupe_hash", "TEXT"),
        ("end_to_end_seconds", "REAL"),
        ("delivery_channel", "TEXT DEFAULT 'INTERNAL_DASHBOARD'"),
        ("delivery_failed", "INTEGER DEFAULT 0"),
        ("scored_by", "TEXT DEFAULT 'llm'"),
    ]:
        try:
            cur.execute(f"ALTER TABLE leads ADD COLUMN {col} {col_type}")
        except Exception:
            pass

    cur.execute("CREATE INDEX IF NOT EXISTS idx_leads_created ON leads (created_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_leads_dedupe ON leads (dedupe_hash, created_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_leads_status ON leads (status)")
    conn.commit()
    conn.close()


_init_sqlite_db()


def compute_dedupe_hash(email: str, message: str) -> str:
    """Computes a sha256 hash of email + message for 5-minute deduplication."""
    clean_str = f"{email.strip().lower()}::{message.strip()}"
    return hashlib.sha256(clean_str.encode("utf-8")).hexdigest()


class LeadRepository:
    """Unified repository for lead storage, deduplication, and pipeline resets."""

    @property
    def storage_engine(self) -> str:
        return "supabase" if supabase_client else "local_sqlite"

    async def find_recent_duplicate(self, email: str, message: str, window_minutes: int = 5) -> Optional[LeadRecord]:
        """Finds any lead with the exact same (email + message) created within the last window_minutes."""
        target_hash = compute_dedupe_hash(email, message)
        cutoff_iso = (datetime.now(timezone.utc) - timedelta(minutes=window_minutes)).isoformat()

        def _check_sqlite():
            conn = sqlite3.connect(settings.SQLITE_PATH)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM leads 
                WHERE dedupe_hash = ? AND created_at >= ?
                ORDER BY created_at DESC LIMIT 1
            """, (target_hash, cutoff_iso))
            row = cur.fetchone()
            conn.close()
            if not row:
                return None
            return self._row_to_lead_record(row)

        return await asyncio.to_thread(_check_sqlite)

    def _row_to_lead_record(self, r: Any) -> LeadRecord:
        keys = r.keys() if hasattr(r, "keys") else []
        return LeadRecord(
            id=r["id"],
            created_at=r["created_at"],
            name=r["name"],
            email=r["email"],
            phone=r["phone"],
            company=r["company"],
            doors=r["doors"],
            message=r["message"],
            fit_score=r["fit_score"],
            reason=r["reason"],
            intent=r["intent"],
            suggested_reply=r["suggested_reply"],
            status=r["status"],
            processing_ms=r["processing_ms"],
            end_to_end_seconds=r["end_to_end_seconds"] if "end_to_end_seconds" in keys and r["end_to_end_seconds"] is not None else (round(r["processing_ms"]/1000.0, 2) if r["processing_ms"] else None),
            delivery_channel=r["delivery_channel"] if "delivery_channel" in keys and r["delivery_channel"] else "INTERNAL_DASHBOARD",
            delivery_failed=bool(r["delivery_failed"]) if "delivery_failed" in keys else False,
            scored_by=r["scored_by"] if "scored_by" in keys and r["scored_by"] else "llm",
            source=r["source"],
            slack_sent=bool(r["slack_sent"]),
            raw_payload=json.loads(r["raw_payload"]) if r["raw_payload"] else None,
        )

    async def save_raw_lead(self, lead: LeadIn, source: str = "facebook_lead_ad") -> str:
        lead_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        payload = lead.model_dump(mode="json")
        dedupe_hash = compute_dedupe_hash(lead.email, lead.message)

        def _insert_sqlite():
            conn = sqlite3.connect(settings.SQLITE_PATH)
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO leads (id, created_at, name, email, phone, company, doors, message, dedupe_hash, source, status, raw_payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'received', ?)
            """, (
                lead_id, now_iso, lead.name, lead.email, lead.phone, lead.company,
                lead.doors, lead.message, dedupe_hash, source, json.dumps(payload)
            ))
            conn.commit()
            conn.close()
            return lead_id

        return await asyncio.to_thread(_insert_sqlite)

    async def update_lead_qualification(
        self,
        lead_id: str,
        qualification: Qualification,
        elapsed_ms: int,
        end_to_end_seconds: float,
        delivery_channel: str,
        delivery_failed: bool = False,
        scored_by: str = "llm",
        slack_sent: bool = False,
    ) -> None:
        def _update_sqlite():
            conn = sqlite3.connect(settings.SQLITE_PATH)
            cur = conn.cursor()
            cur.execute("""
                UPDATE leads
                SET fit_score = ?, reason = ?, intent = ?, suggested_reply = ?,
                    status = 'qualified', processing_ms = ?, end_to_end_seconds = ?,
                    delivery_channel = ?, delivery_failed = ?, scored_by = ?, slack_sent = ?
                WHERE id = ?
            """, (
                qualification.fit_score, qualification.reason, qualification.intent,
                qualification.suggested_reply, elapsed_ms, end_to_end_seconds,
                delivery_channel, 1 if delivery_failed else 0, scored_by,
                1 if slack_sent else 0, lead_id
            ))
            conn.commit()
            conn.close()

        await asyncio.to_thread(_update_sqlite)

    async def mark_lead_failed(self, lead_id: str, error_msg: str, elapsed_ms: int) -> None:
        def _fail_sqlite():
            conn = sqlite3.connect(settings.SQLITE_PATH)
            cur = conn.cursor()
            cur.execute("""
                UPDATE leads
                SET status = 'failed', reason = ?, processing_ms = ?
                WHERE id = ?
            """, (f"Processing error: {error_msg}"[:300], elapsed_ms, lead_id))
            conn.commit()
            conn.close()

        await asyncio.to_thread(_fail_sqlite)

    async def list_leads(self, limit: int = 50, status: Optional[str] = None) -> List[LeadRecord]:
        def _fetch_sqlite():
            conn = sqlite3.connect(settings.SQLITE_PATH)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            if status:
                cur.execute(
                    "SELECT * FROM leads WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status, limit)
                )
            else:
                cur.execute("SELECT * FROM leads ORDER BY created_at DESC LIMIT ?", (limit,))
            rows = cur.fetchall()
            conn.close()
            return [self._row_to_lead_record(r) for r in rows]

        return await asyncio.to_thread(_fetch_sqlite)

    async def get_lead(self, lead_id: str) -> Optional[LeadRecord]:
        def _get_sqlite():
            conn = sqlite3.connect(settings.SQLITE_PATH)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM leads WHERE id = ?", (lead_id,))
            r = cur.fetchone()
            conn.close()
            if not r:
                return None
            return self._row_to_lead_record(r)

        return await asyncio.to_thread(_get_sqlite)

    async def update_status(self, lead_id: str, new_status: str) -> bool:
        def _update_status_sqlite():
            conn = sqlite3.connect(settings.SQLITE_PATH)
            cur = conn.cursor()
            cur.execute("UPDATE leads SET status = ? WHERE id = ?", (new_status, lead_id))
            affected = cur.rowcount
            conn.commit()
            conn.close()
            return affected > 0

        return await asyncio.to_thread(_update_status_sqlite)

    async def reset_leads(self) -> int:
        """Clears all leads from the database for demo data reset."""
        def _clear():
            conn = sqlite3.connect(settings.SQLITE_PATH)
            cur = conn.cursor()
            cur.execute("DELETE FROM leads")
            count = cur.rowcount
            conn.commit()
            conn.close()
            return count

        return await asyncio.to_thread(_clear)

    async def get_analytics(self) -> AnalyticsSummary:
        """Calculates SLA benchmarks, latency statistics, and score distributions."""
        leads = await self.list_leads(limit=500)
        total = len(leads)
        if total == 0:
            return AnalyticsSummary(
                total_leads=0,
                qualified_leads=0,
                avg_processing_ms=0.0,
                under_60_count=0,
                sla_percentage=100.0,
                intent_distribution={"low": 0, "medium": 0, "high": 0},
                score_distribution={1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
                storage_engine=self.storage_engine
            )

        qualified = [l for l in leads if l.fit_score is not None]
        sec_list = [l.end_to_end_seconds for l in qualified if l.end_to_end_seconds is not None]
        avg_sec = round(sum(sec_list) / len(sec_list), 2) if sec_list else 0.0

        under_60 = sum(1 for s in sec_list if s < float(settings.TARGET_SLA_SECONDS))
        sla_pct = round((under_60 / len(sec_list)) * 100, 1) if sec_list else 100.0

        intents = {"low": 0, "medium": 0, "high": 0}
        for l in qualified:
            if l.intent in intents:
                intents[l.intent] += 1

        scores = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for l in qualified:
            if l.fit_score in scores:
                scores[l.fit_score] += 1

        return AnalyticsSummary(
            total_leads=total,
            qualified_leads=len(qualified),
            avg_processing_ms=avg_sec,  # Returned as average seconds for clean display
            under_60_count=under_60,
            sla_percentage=sla_pct,
            intent_distribution=intents,
            score_distribution=scores,
            storage_engine=self.storage_engine
        )


repository = LeadRepository()
