import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app_core.config import settings
from app_core.routes.health import router as health_router
from app_core.routes.leads import router as leads_router
from app_core.routes.webhooks import router as webhooks_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("speed-to-lead")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown hooks."""
    logger.info("⚡ Speed-to-Lead Automation MVP initializing...")
    logger.info("Target SLA: < %d seconds (Replacing 22-hour delay)", settings.TARGET_SLA_SECONDS)
    logger.info("Storage Engine: %s", "Supabase" if settings.is_supabase_configured else "Local SQLite (zero-config)")
    logger.info("AI Qualifier: %s (%s)", "OpenAI" if settings.is_openai_configured else "Heuristic Engine", settings.OPENAI_MODEL)
    logger.info("Slack Alerts: %s", "Active" if settings.is_slack_configured else "Simulated/Demo")
    logger.info("Discord Alerts: %s", "Active" if settings.is_discord_configured else "Inactive")
    yield
    logger.info("Speed-to-Lead Automation shutting down.")


app = FastAPI(
    title="Speed-to-Lead Automation MVP",
    description="Sub-60s inbound lead qualification & immediate reply dispatcher",
    version="2.0.0",
    lifespan=lifespan,
)

# Enable CORS for web clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(health_router)
app.include_router(webhooks_router)
app.include_router(leads_router)

# Mount Static Files and Serve Dashboard UI
static_dir = Path(__file__).resolve().parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", include_in_schema=False)
async def serve_index():
    """Serves the interactive Speed-to-Lead Dashboard."""
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Speed-to-Lead Automation MVP API is running. Visit /docs for API schema."}
