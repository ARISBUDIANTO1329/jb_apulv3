from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
from pathlib import Path

from app.core.config import settings
from app.db.session import engine
from app.models.base import Base
from app.api import channels, media, production, uploads, livestream, pipeline, auth
from app.api import google_auth
from app.api import shorts
from app.api import ai
from app.api import youtube_api
from app.api import thumbnail
from app.api import estafet
from app.api import metadata


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create database tables on startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title="JB APUL v3",
    description="YouTube Automation Platform",
    version="3.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files & templates
BASE_DIR = Path(__file__).resolve().parent.parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.mount("/storage", StaticFiles(directory="/app/storage"), name="storage")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
app.include_router(channels.router, prefix="/api/channels", tags=["Channels"])
app.include_router(media.router, prefix="/api/media", tags=["Media"])
app.include_router(google_auth.router, prefix="/api/auth/google", tags=["Google Auth"])
app.include_router(production.router, prefix="/api/production", tags=["Production"])
app.include_router(uploads.router, prefix="/api/uploads", tags=["Uploads"])
app.include_router(livestream.router, prefix="/api/livestream", tags=["Livestream"])
app.include_router(pipeline.router, prefix="/api/pipeline", tags=["Pipeline"])
app.include_router(shorts.router, prefix="/api/shorts", tags=["Shorts"])
app.include_router(estafet.router, prefix="/api/estafet", tags=["Estafet"])
app.include_router(metadata.router, prefix="/api/metadata", tags=["Metadata"])
app.include_router(ai.router, prefix="/api/ai", tags=["AI"])
app.include_router(youtube_api.router, prefix="/api/youtube", tags=["YouTube API"])
app.include_router(thumbnail.router, prefix="/api/thumbnail", tags=["Thumbnail"])


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "3.0.0"}


@app.get("/api/system/stats")
async def system_stats():
    """Get CPU and memory usage."""
    import subprocess

    # CPU usage
    try:
        top_result = subprocess.run(["top", "-bn1"], capture_output=True, text=True, timeout=5)
        cpu_line = [l for l in top_result.stdout.splitlines() if "Cpu(s)" in l or "%Cpu" in l]
        if cpu_line:
            parts = cpu_line[0].split(",")
            idle = 0
            for p in parts:
                if "id" in p:
                    idle = float(p.strip().split()[0])
            cpu_percent = round(100 - idle, 1)
        else:
            cpu_percent = 0
    except Exception:
        cpu_percent = 0

    # Memory usage
    try:
        mem_result = subprocess.run(["free", "-m"], capture_output=True, text=True, timeout=5)
        lines = mem_result.stdout.splitlines()
        if len(lines) >= 2:
            parts = lines[1].split()
            total_mb = int(parts[1])
            used_mb = int(parts[2])
            mem_percent = round((used_mb / total_mb) * 100, 1) if total_mb > 0 else 0
        else:
            total_mb = used_mb = 0
            mem_percent = 0
    except Exception:
        total_mb = used_mb = 0
        mem_percent = 0

    # Disk usage
    try:
        disk_result = subprocess.run(["df", "-h", "/"], capture_output=True, text=True, timeout=5)
        lines = disk_result.stdout.splitlines()
        if len(lines) >= 2:
            parts = lines[1].split()
            disk_total = parts[1]
            disk_used = parts[2]
            disk_percent = int(parts[4].replace("%", ""))
        else:
            disk_total = disk_used = "N/A"
            disk_percent = 0
    except Exception:
        disk_total = disk_used = "N/A"
        disk_percent = 0

    return {
        "cpu_percent": cpu_percent,
        "memory": {"total_mb": total_mb, "used_mb": used_mb, "percent": mem_percent},
        "disk": {"total": disk_total, "used": disk_used, "percent": disk_percent},
    }


# ── HTML Pages ──────────────────────────────────────────────────

@app.get("/")
async def page_dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", {"page": "dashboard"})


@app.get("/media")
async def page_media(request: Request, group: str = "video", q: str = ""):
    from app.api.media import GROUP_META
    from app.db.session import async_session
    from app.models.channel import Channel
    from sqlalchemy import select

    # Get first channel as default (or None)
    async with async_session() as db:
        result = await db.execute(select(Channel).limit(1))
        channel = result.scalar_one_or_none()

    channel_data = None
    if channel:
        channel_data = {"id": channel.id, "name": channel.name}

    return templates.TemplateResponse(request, "media.html", {
        "page": "media",
        "activeChannel": channel_data,
    })


@app.get("/production")
async def page_production(request: Request):
    return templates.TemplateResponse(request, "production.html", {"page": "production"})



@app.get("/uploads")
async def page_uploads(request: Request):
    return templates.TemplateResponse(request, "uploads.html", {"page": "uploads"})


@app.get("/monitor-upload")
async def page_monitor_upload(request: Request):
    return templates.TemplateResponse(request, "monitor-upload.html", {"page": "monitor-upload"})


@app.get("/live")
async def page_live(request: Request):
    return templates.TemplateResponse(request, "live.html", {"page": "live"})


@app.get("/monitor-live")
async def page_monitor_live(request: Request):
    return templates.TemplateResponse(request, "monitor-live.html", {"page": "monitor-live"})


@app.get("/estafet")
async def page_estafet(request: Request):
    return templates.TemplateResponse(request, "estafet.html", {"page": "estafet"})


@app.get("/pipeline")
async def page_pipeline(request: Request):
    return templates.TemplateResponse(request, "pipeline.html", {"page": "pipeline"})


@app.get("/shorts")
async def page_shorts(request: Request):
    return templates.TemplateResponse(request, "shorts.html", {"page": "shorts"})


@app.get("/monitor-shorts")
async def page_monitor_shorts(request: Request):
    return templates.TemplateResponse(request, "monitor-shorts.html", {"page": "monitor-shorts"})


@app.get("/ai-settings")
async def page_ai_settings(request: Request):
    return templates.TemplateResponse(request, "ai-settings.html", {"page": "ai-settings"})
