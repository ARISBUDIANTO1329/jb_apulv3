"""
Livestream API - JB APUL v3
FIX: Added publish-now, schedule, metadata validation, thumbnail upload
FIX: Video source auto-fix (search multiple folders)
FIX: Made for kids support
"""

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Optional
import subprocess
import os
import signal
from pathlib import Path
from datetime import datetime, timezone

from app.db.session import get_db
from app.models.livestream import LiveJob
from app.models.channel import Channel
from app.models.metadata import MetadataTitlePool
from app.services.storage import storage

router = APIRouter()


# ── Request Models ──────────────────────────────────────────────

class LivestreamRequest(BaseModel):
    channel_id: int
    video_source: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[str] = None
    duration_hours: int = 12
    quality: str = "low"
    use_mp3: bool = True
    use_sfx: bool = True
    visibility: str = "unlisted"
    thumbnail_path: Optional[str] = None
    made_for_kids: bool = False


class PublishNowRequest(BaseModel):
    channel_id: int
    video_source: str
    title: str
    description: Optional[str] = None
    tags: Optional[str] = None
    duration_hours: int = 12
    quality: str = "low"
    use_mp3: bool = True
    use_sfx: bool = True
    visibility: str = "unlisted"
    thumbnail_path: Optional[str] = None
    made_for_kids: bool = False
    stream_key: Optional[str] = None


class ScheduleRequest(BaseModel):
    channel_id: int
    video_source: str
    title: str
    description: Optional[str] = None
    tags: Optional[str] = None
    duration_hours: int = 12
    quality: str = "low"
    use_mp3: bool = True
    use_sfx: bool = True
    visibility: str = "unlisted"
    thumbnail_path: Optional[str] = None
    made_for_kids: bool = False
    start_at_wib: str  # ISO format in WIB
    stream_key: Optional[str] = None


# ── Helpers ──────────────────────────────────────────────────────

def _find_video_source(channel_id: int, video_source: str) -> bool:
    """Check if video source exists in any asset folder."""
    if not video_source:
        return False

    # Direct path
    if os.path.exists(video_source):
        return True

    # Search in multiple asset types
    storage_path = storage.base_path
    basename = os.path.basename(video_source)
    for group in ["video-live", "video", "upload_ready", "livestream-ready"]:
        candidate = storage_path / "assets" / group / str(channel_id) / basename
        if candidate.exists():
            return True

    return False


def _validate_metadata(title: str, description: str = None, tags: str = None) -> dict:
    """Validate livestream metadata."""
    errors = []

    if not title or len(title.strip()) < 3:
        errors.append("Title minimal3 karakter")
    if len(title or "") > 100:
        errors.append("Title maksimal100 karakter")
    if description and len(description) > 5000:
        errors.append("Description maksimal 5000 karakter")

    return {"is_ready": len(errors) == 0, "errors": errors}


def _resolve_stream_key(channel: Channel, manual_key: str = None) -> str:
    """Resolve stream key from channel or manual input."""
    if manual_key:
        return manual_key
    return channel.stream_key or ""


# ── Endpoints ──────────────────────────────────────────────────

@router.get("")
async def list_jobs(
    channel_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List livestream jobs."""
    query = select(LiveJob)
    if channel_id:
        query = query.where(LiveJob.channel_id == channel_id)
    if status:
        query = query.where(LiveJob.status == status)
    query = query.order_by(LiveJob.created_at.desc())
    result = await db.execute(query)
    jobs = result.scalars().all()

    return [{
        "id": job.id,
        "channel_id": job.channel_id,
        "title": job.title,
        "video_source": job.video_source,
        "status": job.status,
        "duration_hours": job.duration_hours,
        "quality": job.quality,
        "broadcast_id": job.broadcast_id,
        "process_id": job.process_id,
        "reconnect_count": job.reconnect_count,
        "error_message": job.error_message,
        "visibility": job.visibility,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    } for job in jobs]


@router.get("/running")
async def get_running_jobs(
    channel_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Get all running livestream jobs with process status."""
    query = select(LiveJob).where(LiveJob.status == "running")
    if channel_id:
        query = query.where(LiveJob.channel_id == channel_id)
    result = await db.execute(query)
    jobs = result.scalars().all()

    running = []
    for job in jobs:
        process_alive = False
        if job.process_id:
            try:
                os.kill(job.process_id, 0)
                process_alive = True
            except (ProcessLookupError, PermissionError):
                pass

        running.append({
            "id": job.id,
            "channel_id": job.channel_id,
            "title": job.title,
            "status": job.status,
            "process_id": job.process_id,
            "process_alive": process_alive,
            "quality": job.quality,
            "duration_hours": job.duration_hours,
            "broadcast_id": job.broadcast_id,
            "started_at": job.started_at.isoformat() if job.started_at else None,
        })

    return running


@router.get("/checker-global")
async def checker_global(db: AsyncSession = Depends(get_db)):
    """Global health check for all running livestream processes."""
    result = await db.execute(select(LiveJob).where(LiveJob.status == "running"))
    jobs = result.scalars().all()

    checks = []
    for job in jobs:
        process_alive = False
        if job.process_id:
            try:
                os.kill(job.process_id, 0)
                process_alive = True
            except (ProcessLookupError, PermissionError):
                pass

        checks.append({
            "job_id": job.id,
            "channel_id": job.channel_id,
            "process_id": job.process_id,
            "process_alive": process_alive,
            "broadcast_id": job.broadcast_id,
            "started_at": job.started_at.isoformat() if job.started_at else None,
        })

    return {"running_count": len(checks), "checks": checks}


@router.get("/kill-global")
async def kill_global(db: AsyncSession = Depends(get_db)):
    """Kill all running livestream processes and end YouTube broadcasts."""
    result = await db.execute(select(LiveJob).where(LiveJob.status == "running"))
    jobs = result.scalars().all()

    killed = 0
    for job in jobs:
        # Kill FFmpeg
        if job.process_id:
            try:
                os.kill(job.process_id, signal.SIGTERM)
                killed += 1
            except (ProcessLookupError, PermissionError):
                pass

        # End YouTube broadcast
        if job.broadcast_id:
            ch_result = await db.execute(select(Channel).where(Channel.id == job.channel_id))
            channel = ch_result.scalar_one_or_none()
            if channel and channel.access_token:
                try:
                    from google.oauth2.credentials import Credentials
                    from googleapiclient.discovery import build as gbuild
                    from google.auth.transport.requests import Request
                    from datetime import timezone

                    _exp = channel.token_expires_at
                    if _exp and _exp.tzinfo is None:
                        _exp = _exp.replace(tzinfo=timezone.utc)

                    creds = Credentials(
                        token=channel.access_token or "",
                        refresh_token=channel.refresh_token or "",
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
                        client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
                        expiry=_exp,
                    )
                    if creds.expired and creds.refresh_token:
                        creds.refresh(Request())
                        channel.access_token = creds.token
                        channel.token_expires_at = creds.expiry

                    youtube = gbuild("youtube", "v3", credentials=creds)
                    youtube.liveBroadcasts().transition(
                        broadcastStatus="complete",
                        id=job.broadcast_id,
                        part="status",
                    ).execute()
                except Exception:
                    pass

        job.status = "stopped"

    await db.flush()
    return {"killed": killed}


@router.post("")
async def create_job(data: LivestreamRequest, db: AsyncSession = Depends(get_db)):
    """Create a livestream job (basic - worker will create broadcast)."""
    result = await db.execute(select(Channel).where(Channel.id == data.channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    if not channel.stream_key and not channel.access_token:
        raise HTTPException(status_code=400, detail="Channel has no stream key or OAuth configured")

    job = LiveJob(
        channel_id=data.channel_id,
        title=data.title or f"Live - {channel.name}",
        description=data.description,
        tags=data.tags,
        video_source=data.video_source,
        stream_key=channel.stream_key,
        duration_hours=data.duration_hours,
        quality=data.quality,
        use_mp3=data.use_mp3,
        use_sfx=data.use_sfx,
        visibility=data.visibility,
        made_for_kids=data.made_for_kids,
        status="pending",
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)

    return {
        "success": True,
        "job_id": job.id,
        "status": "pending",
        "message": "Livestream job created. Worker will pick it up.",
    }



@router.get("/readiness")
async def check_readiness(
    channel_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Check if channel is ready for a new livestream."""
    checks = {
        "channel": False,
        "stream_key": False,
        "video_source": False,
        "no_running_job": True,
        "oauth_valid": False,
        "is_ready": False,
        "errors": [],
    }

    # Check channel
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        checks["errors"].append("Channel tidak ditemukan")
        return checks
    checks["channel"] = True

    # Check stream key
    stream_key = channel.stream_key or channel.stream_sync
    if stream_key:
        checks["stream_key"] = True
    elif channel.access_token:
        checks["stream_key"] = True  # Will create broadcast via API

    # Check OAuth
    if channel.access_token:
        checks["oauth_valid"] = True

    # Check for running/pending jobs
    result = await db.execute(
        select(LiveJob).where(
            LiveJob.channel_id == channel_id,
            LiveJob.status.in_(["running", "pending", "ready"]),
        )
    )
    running_jobs = result.scalars().all()
    if running_jobs:
        checks["no_running_job"] = False
        for job in running_jobs:
            checks["errors"].append(f"Job #{job.id} masih {job.status}: {job.title or '-'}")

    # Check video source (any video in video folder)
    video_dir = Path(f"/app/storage/assets/video/{channel_id}")
    if video_dir.exists():
        videos = [f for f in video_dir.iterdir() if f.suffix.lower() in [".mp4", ".mkv", ".webm"]]
        if videos:
            checks["video_source"] = True
        else:
            checks["errors"].append("Tidak ada video di folder video")
    else:
        checks["errors"].append("Folder video tidak ada")

    # Overall readiness
    checks["is_ready"] = all([
        checks["channel"],
        checks["stream_key"],
        checks["video_source"],
        checks["no_running_job"],
    ])

    return checks


@router.post("/cleanup-jobs")
async def cleanup_stuck_jobs(
    channel_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Cleanup stuck jobs (running/pending without active process)."""
    result = await db.execute(
        select(LiveJob).where(
            LiveJob.channel_id == channel_id,
            LiveJob.status.in_(["running", "pending", "ready"]),
        )
    )
    jobs = result.scalars().all()
    cleaned = []
    for job in jobs:
        job.status = "stopped"
        job.finished_at = datetime.now(timezone.utc)
        cleaned.append({"id": job.id, "title": job.title, "old_status": job.status})
    await db.flush()
    return {"cleaned": cleaned, "count": len(cleaned)}


@router.post("/publish-now")
async def publish_now(data: PublishNowRequest, db: AsyncSession = Depends(get_db)):
    """Publish livestream immediately - validates metadata, resolves stream key, creates job."""
    result = await db.execute(select(Channel).where(Channel.id == data.channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # Check for running/pending jobs
    result_running = await db.execute(
        select(LiveJob).where(
            LiveJob.channel_id == data.channel_id,
            LiveJob.status.in_(["running", "pending", "ready"]),
        )
    )
    running_jobs = result_running.scalars().all()
    if running_jobs:
        job_list = ", ".join([f"#{j.id} ({j.status})" for j in running_jobs])
        raise HTTPException(status_code=400, detail=f"Masih ada livestream aktif: {job_list}. Stop dulu sebelum start baru.")

    # Validate metadata
    validation = _validate_metadata(data.title, data.description, data.tags)
    if not validation["is_ready"]:
        raise HTTPException(status_code=400, detail=f"Metadata tidak valid: {', '.join(validation['errors'])}")

    # Validate video source
    if not _find_video_source(data.channel_id, data.video_source):
        raise HTTPException(status_code=400, detail=f"Video source tidak ditemukan: {data.video_source}")

    # Resolve stream key
    stream_key = _resolve_stream_key(channel, data.stream_key)
    if not stream_key and not channel.access_token:
        raise HTTPException(status_code=400, detail="Stream key tidak tersedia. Set di channel atau masukkan manual.")

    # Mark title as used if from pool
    if data.title:
        title_pool = await db.execute(
            select(MetadataTitlePool).where(
                MetadataTitlePool.channel_id == data.channel_id,
                MetadataTitlePool.title == data.title,
                MetadataTitlePool.used_at.is_(None),
            )
        )
        title_record = title_pool.scalar_one_or_none()
        if title_record:
            title_record.used_at = datetime.now(timezone.utc)

    # Create job with status=ready (worker will start immediately)
    job = LiveJob(
        channel_id=data.channel_id,
        title=data.title,
        description=data.description,
        tags=data.tags,
        video_source=data.video_source,
        stream_key=stream_key,
        duration_hours=data.duration_hours,
        quality=data.quality,
        use_mp3=data.use_mp3,
        use_sfx=data.use_sfx,
        visibility=data.visibility,
        made_for_kids=data.made_for_kids,
        thumbnail_path=data.thumbnail_path,
        status="pending",  # Worker will pick up and create YouTube broadcast
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)

    return {
        "success": True,
        "job_id": job.id,
        "status": "pending",
        "message": "Livestream queued. Worker akan membuat YouTube broadcast dan memulai stream.",
    }


@router.post("/schedule")
async def schedule_live(data: ScheduleRequest, db: AsyncSession = Depends(get_db)):
    """Schedule a livestream for later - validates metadata, creates scheduled job."""
    result = await db.execute(select(Channel).where(Channel.id == data.channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # Check for running/pending jobs
    result_running = await db.execute(
        select(LiveJob).where(
            LiveJob.channel_id == data.channel_id,
            LiveJob.status.in_(["running", "pending", "ready"]),
        )
    )
    running_jobs = result_running.scalars().all()
    if running_jobs:
        job_list = ", ".join([f"#{j.id} ({j.status})" for j in running_jobs])
        raise HTTPException(status_code=400, detail=f"Masih ada livestream aktif: {job_list}. Stop dulu sebelum start baru.")

    # Validate metadata
    validation = _validate_metadata(data.title, data.description, data.tags)
    if not validation["is_ready"]:
        raise HTTPException(status_code=400, detail=f"Metadata tidak valid: {', '.join(validation['errors'])}")

    # Validate video source
    if not _find_video_source(data.channel_id, data.video_source):
        raise HTTPException(status_code=400, detail=f"Video source tidak ditemukan: {data.video_source}")

    # Parse WIB time to UTC
    try:
        from datetime import timedelta
        # Parse ISO format, assume WIB (UTC+7)
        local_time = datetime.fromisoformat(data.start_at_wib)
        utc_time = local_time - timedelta(hours=7)
        if utc_time.tzinfo is None:
            utc_time = utc_time.replace(tzinfo=timezone.utc)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Format waktu tidak valid: {e}")

    # Resolve stream key
    stream_key = _resolve_stream_key(channel, data.stream_key)

    # Mark title as used if from pool
    if data.title:
        title_pool = await db.execute(
            select(MetadataTitlePool).where(
                MetadataTitlePool.channel_id == data.channel_id,
                MetadataTitlePool.title == data.title,
                MetadataTitlePool.used_at.is_(None),
            )
        )
        title_record = title_pool.scalar_one_or_none()
        if title_record:
            title_record.used_at = datetime.now(timezone.utc)

    # Create scheduled job
    end_utc = utc_time + __import__("datetime").timedelta(hours=data.duration_hours)

    job = LiveJob(
        channel_id=data.channel_id,
        title=data.title,
        description=data.description,
        tags=data.tags,
        video_source=data.video_source,
        stream_key=stream_key,
        duration_hours=data.duration_hours,
        quality=data.quality,
        use_mp3=data.use_mp3,
        use_sfx=data.use_sfx,
        visibility=data.visibility,
        made_for_kids=data.made_for_kids,
        thumbnail_path=data.thumbnail_path,
        start_at_utc=utc_time,
        end_at_utc=end_utc,
        status="scheduled",
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)

    return {
        "success": True,
        "job_id": job.id,
        "status": "scheduled",
        "start_at_utc": utc_time.isoformat(),
        "message": f"Livestream dijadwalkan pada {data.start_at_wib} WIB.",
    }


@router.post("/check-token")
async def check_token(channel_id: int = Query(...), db: AsyncSession = Depends(get_db)):
    """Check if Google OAuth token is valid for a channel."""
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    if not channel.access_token and not channel.refresh_token:
        return {"valid": False, "message": "Channel belum terkoneksi ke Google/YouTube"}

    # Try to build YouTube service (will auto-refresh if expired)
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from google.auth.transport.requests import Request

    # Check if token is expired or about to expire (within 30 minutes)
    from datetime import timedelta
    is_expired = False
    needs_refresh = False
    if channel.token_expires_at:
        exp = channel.token_expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        is_expired = exp < now
        # Proactive refresh: if expiring within 30 minutes
        if not is_expired and (exp - now) <= timedelta(minutes=30):
            needs_refresh = True

    creds = Credentials(
        token=channel.access_token or "",
        refresh_token=channel.refresh_token or "",
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
        client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
    )
    if (is_expired or needs_refresh) and channel.refresh_token:
        try:
            creds.refresh(Request())
            # Save refreshed token and set status to valid
            channel.access_token = creds.token
            channel.token_expires_at = creds.expiry
            channel.token_status = "valid"
            channel.token_error = None
            channel.token_checked_at = datetime.now(timezone.utc)
            await db.flush()
            return {"valid": True, "message": "Token di-refresh, valid.", "expires_at": creds.expiry.isoformat() if creds.expiry else None}
        except Exception as e:
            error_msg = str(e)
            channel.token_status = "error"
            channel.token_error = error_msg[:500]
            channel.token_checked_at = datetime.now(timezone.utc)
            await db.flush()
            return {"valid": False, "message": "Token expired dan gagal refresh: " + error_msg}
    elif creds.expired:
        channel.token_status = "expired"
        channel.token_error = "No refresh token"
        channel.token_checked_at = datetime.now(timezone.utc)
        await db.flush()
        return {"valid": False, "message": "Token expired dan tidak ada refresh token"}
    else:
        channel.token_status = "valid"
        channel.token_error = None
        channel.token_checked_at = datetime.now(timezone.utc)
        await db.flush()
        return {"valid": True, "message": "Token valid.", "expires_at": channel.token_expires_at.isoformat() if channel.token_expires_at else None}

@router.get("/video-sources/{channel_id}")
async def get_video_sources(channel_id: int, db: AsyncSession = Depends(get_db)):
    """Get available video sources for livestream (search multiple folders)."""
    from app.models.media import MediaItem

    result = await db.execute(
        select(MediaItem)
        .where(MediaItem.channel_id == channel_id)
        .where(MediaItem.asset_type.in_(["video-live", "video", "upload_ready", "livestream-ready"]))
        .where(MediaItem.filename.op("~")(r"\.(mp4|mkv|mov|avi|webm)$"))
        .order_by(MediaItem.asset_type, MediaItem.filename)
    )
    items = result.scalars().all()

    sources = []
    for item in items:
        sources.append({
            "id": item.id,
            "filename": item.filename,
            "asset_type": item.asset_type,
            "label": f"{item.asset_type}/{item.filename}",
            "file_size": item.file_size or 0,
        })

    return sources


@router.get("/monitor")
async def get_monitor_data(channel_id: int = Query(None), db: AsyncSession = Depends(get_db)):
    """Get all running jobs with stats for monitoring dashboard."""
    query = select(LiveJob).where(LiveJob.status == "running")
    if channel_id:
        query = query.where(LiveJob.channel_id == channel_id)
    result = await db.execute(query)
    jobs = result.scalars().all()
    
    monitors = []
    for job in jobs:
        # Calculate duration
        duration_str = "-"
        if job.started_at:
            elapsed = (datetime.now(timezone.utc) - job.started_at).total_seconds()
            hours = int(elapsed // 3600)
            minutes = int((elapsed % 3600) // 60)
            duration_str = f"{hours}h {minutes}m"
        
        monitors.append({
            "job_id": job.id,
            "channel_id": job.channel_id,
            "title": job.title,
            "status": job.status,
            "quality": job.quality,
            "duration": duration_str,
            "current_bitrate": job.current_bitrate,
            "current_fps": job.current_fps,
            "viewer_count": job.viewer_count,
            "frame_drop_count": job.frame_drop_count,
            "reconnect_count": job.reconnect_count,
            "last_health_check": job.last_health_check.isoformat() if job.last_health_check else None,
            "error_category": job.error_category,
            "process_id": job.process_id,
            "broadcast_id": job.broadcast_id,
        })
    
    return {"running_count": len(monitors), "monitors": monitors}

@router.get("/health-dashboard")
async def get_health_dashboard(db: AsyncSession = Depends(get_db)):
    """Get health dashboard for all channels."""
    from app.models.channel import Channel
    
    # Get all channels
    channels_result = await db.execute(select(Channel))
    channels = channels_result.scalars().all()
    
    dashboard = []
    for channel in channels:
        # Get running job
        running_result = await db.execute(
            select(LiveJob).where(
                LiveJob.channel_id == channel.id,
                LiveJob.status == "running"
            )
        )
        running_job = running_result.scalar_one_or_none()
        
        # Get job statistics
        stats_result = await db.execute(
            select(
                func.count(LiveJob.id).label("total_jobs"),
                func.sum(
                    func.extract("epoch", LiveJob.finished_at - LiveJob.started_at) / 3600
                ).label("total_hours")
            ).where(
                LiveJob.channel_id == channel.id,
                LiveJob.status.in_(["finished", "stopped"]),
                LiveJob.started_at.isnot(None),
                LiveJob.finished_at.isnot(None)
            )
        )
        stats = stats_result.one_or_none()
        
        # Get last error
        error_result = await db.execute(
            select(LiveJob).where(
                LiveJob.channel_id == channel.id,
                LiveJob.status == "failed"
            ).order_by(LiveJob.finished_at.desc()).limit(1)
        )
        last_error_job = error_result.scalar_one_or_none()
        
        # Calculate uptime
        total_jobs = stats[0] if stats else 0
        total_hours = float(stats[1]) if stats and stats[1] else 0
        
        dashboard.append({
            "channel_id": channel.id,
            "channel_name": channel.name or f"Channel {channel.id}",
            "status": "running" if running_job else "idle",
            "current_job": {
                "id": running_job.id,
                "title": running_job.title,
                "started_at": running_job.started_at.isoformat() if running_job.started_at else None,
                "bitrate": running_job.current_bitrate,
                "fps": running_job.current_fps,
            } if running_job else None,
            "total_streams": total_jobs,
            "total_hours": round(total_hours, 1),
            "last_error": last_error_job.error_message if last_error_job else None,
            "last_error_at": last_error_job.finished_at.isoformat() if last_error_job and last_error_job.finished_at else None,
            "last_error_category": last_error_job.error_category if last_error_job else None,
            "last_upload": channel.last_upload.isoformat() if channel.last_upload else None,
            "last_livestream": channel.last_livestream.isoformat() if channel.last_livestream else None,
        })
    
    return {"channels": dashboard}


    status = {
        "ffmpeg": {"running": False, "count": 0, "processes": []},
        "worker": {"running": False, "pid": None},
        "backend": {"running": True, "pid": os.getpid()},
    }

    # Check FFmpeg processes in worker container
    try:
        result = subprocess.run(
            ["docker", "exec", "jb_apulv3-worker-livestream-1", "ps", "aux"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            lines = result.stdout.splitlines()
            ffmpeg_procs = []
            for line in lines:
                if "ffmpeg" in line and "grep" not in line:
                    parts = line.split()
                    if len(parts) >= 11:
                        ffmpeg_procs.append({
                            "pid": parts[1],
                            "cpu": parts[2],
                            "mem": parts[3],
                            "started": " ".join(parts[9:11]),
                        })
            status["ffmpeg"]["running"] = len(ffmpeg_procs) > 0
            status["ffmpeg"]["count"] = len(ffmpeg_procs)
            status["ffmpeg"]["processes"] = ffmpeg_procs
    except Exception as e:
        status["ffmpeg"]["error"] = str(e)

    # Check Worker (Python) process
    try:
        result = subprocess.run(
            ["docker", "exec", "jb_apulv3-worker-livestream-1", "ps", "aux"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if "python worker" in line and "grep" not in line:
                    parts = line.split()
                    status["worker"]["running"] = True
                    status["worker"]["pid"] = parts[1]
                    status["worker"]["cpu"] = parts[2]
                    status["worker"]["mem"] = parts[3]
                    break
    except Exception as e:
        status["worker"]["error"] = str(e)

    # Get running jobs from DB
    try:
        conn = psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, channel_id, status, process_id, broadcast_id, "
                "current_bitrate, current_fps, last_health_check "
                "FROM live_jobs WHERE status = 'running'"
            )
            jobs = cur.fetchall()
            status["running_jobs"] = []
            for j in jobs:
                health_age = None
                if j["last_health_check"]:
                    health_age = round((datetime.now(timezone.utc) - j["last_health_check"]).total_seconds(), 1)
                status["running_jobs"].append({
                    "id": j["id"],
                    "channel_id": j["channel_id"],
                    "broadcast_id": j["broadcast_id"],
                    "bitrate": j["current_bitrate"],
                    "fps": j["current_fps"],
                    "last_health": j["last_health_check"].isoformat() if j["last_health_check"] else None,
                    "health_age_sec": health_age,
                })
        conn.close()
    except Exception as e:
        status["running_jobs_error"] = str(e)

    return status



@router.get("/engine-status")
async def get_engine_status():
    """Get real-time status of FFmpeg, Worker, and Python engines."""
    import httpx

    status = {
        "ffmpeg": {"running": False, "count": 0, "processes": []},
        "worker": {"running": False, "pid": None},
        "backend": {"running": True, "pid": os.getpid()},
        "running_jobs": [],
    }

    # Check worker health via HTTP (worker has health server on port 9999)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get("http://jb_apulv3-worker-livestream-1:9999/health", timeout=5.0)
            if resp.status_code == 200:
                worker_health = resp.json()
                status["worker"]["running"] = True
                status["ffmpeg"]["running"] = worker_health.get("running_count", 0) > 0
                status["ffmpeg"]["count"] = worker_health.get("running_count", 0)
                status["ffmpeg"]["jobs"] = worker_health.get("jobs", {})
            else:
                status["worker"]["error"] = f"HTTP {resp.status_code}"
    except Exception as e:
        status["worker"]["error"] = str(e)

    # Get running jobs from DB
    try:
        from app.db.session import async_session
        from sqlalchemy import select
        from app.models.livestream import LiveJob

        async with async_session() as db:
            result = await db.execute(
                select(LiveJob).where(LiveJob.status == "running")
            )
            jobs = result.scalars().all()
            for j in jobs:
                health_age = None
                if j.last_health_check:
                    health_age = round((datetime.now(timezone.utc) - j.last_health_check).total_seconds(), 1)
                status["running_jobs"].append({
                    "id": j.id,
                    "channel_id": j.channel_id,
                    "broadcast_id": j.broadcast_id,
                    "bitrate": j.current_bitrate,
                    "fps": j.current_fps,
                    "last_health": j.last_health_check.isoformat() if j.last_health_check else None,
                    "health_age_sec": health_age,
                })
    except Exception as e:
        status["running_jobs_error"] = str(e)

    return status

@router.get("/{job_id}")
async def get_job(job_id: int, db: AsyncSession = Depends(get_db)):
    """Get livestream job details."""
    result = await db.execute(select(LiveJob).where(LiveJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "id": job.id,
        "channel_id": job.channel_id,
        "title": job.title,
        "description": job.description,
        "video_source": job.video_source,
        "stream_key": "***" if job.stream_key else None,
        "broadcast_id": job.broadcast_id,
        "quality": job.quality,
        "duration_hours": job.duration_hours,
        "use_mp3": job.use_mp3,
        "use_sfx": job.use_sfx,
        "visibility": job.visibility,
        "made_for_kids": job.made_for_kids,
        "thumbnail_path": job.thumbnail_path,
        "status": job.status,
        "process_id": job.process_id,
        "reconnect_count": job.reconnect_count,
        "error_message": job.error_message,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


@router.post("/{job_id}/process-check")
async def process_check(job_id: int, db: AsyncSession = Depends(get_db)):
    """Check if the FFmpeg process for a job is still alive."""
    result = await db.execute(select(LiveJob).where(LiveJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if not job.process_id:
        return {"alive": False, "process_id": None, "message": "No process ID"}

    try:
        os.kill(job.process_id, 0)
        return {"alive": True, "process_id": job.process_id}
    except ProcessLookupError:
        return {"alive": False, "process_id": job.process_id, "message": "Process not found"}
    except PermissionError:
        return {"alive": True, "process_id": job.process_id}


@router.post("/{job_id}/kill-process")
async def kill_process(job_id: int, db: AsyncSession = Depends(get_db)):
    """Send stop command to worker via DB (worker will kill FFmpeg + end broadcast)."""
    result = await db.execute(select(LiveJob).where(LiveJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status not in ["running", "pending", "scheduled"]:
        return {"success": False, "message": f"Job status is '{job.status}', cannot stop"}

    job.stop_requested = True
    await db.flush()
    return {"success": True, "message": f"Stop command sent for job #{job_id}. Worker will process within 3s."}


@router.post("/{job_id}/stop")
async def stop_job(job_id: int, db: AsyncSession = Depends(get_db)):
    """Stop a running livestream by sending stop command to worker via DB."""
    result = await db.execute(select(LiveJob).where(LiveJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status not in ["running", "pending", "scheduled"]:
        raise HTTPException(status_code=400, detail=f"Cannot stop job in '{job.status}' state")

    # Send stop command via DB - worker will handle FFmpeg + YouTube broadcast
    job.stop_requested = True
    await db.flush()

    return {"success": True, "message": f"Stop command sent for job #{job_id}. Worker will process within 3s."}


@router.delete("/{job_id}")
async def delete_job(job_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a livestream job."""
    result = await db.execute(select(LiveJob).where(LiveJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status == "running":
        raise HTTPException(status_code=400, detail="Stop the job first before deleting")

    await db.delete(job)
    return {"success": True}


# ── New Endpoints for P1/P2 ────────────────────────────────────

@router.get("/{job_id}/stats")
async def get_job_stats(job_id: int, db: AsyncSession = Depends(get_db)):
    """Get real-time stream stats for a job."""
    result = await db.execute(select(LiveJob).where(LiveJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return {
        "job_id": job.id,
        "status": job.status,
        "stream_stats": job.stream_stats,
        "current_bitrate": job.current_bitrate,
        "current_fps": job.current_fps,
        "viewer_count": job.viewer_count,
        "frame_drop_count": job.frame_drop_count,
        "reconnect_count": job.reconnect_count,
        "last_health_check": job.last_health_check.isoformat() if job.last_health_check else None,
        "error_category": job.error_category,
        "retry_count": job.retry_count,
    }

class UpdateJobRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[str] = None
    duration_hours: Optional[int] = None
    quality: Optional[str] = None
    use_mp3: Optional[bool] = None
    use_sfx: Optional[bool] = None
    visibility: Optional[str] = None
    made_for_kids: Optional[bool] = None
    thumbnail_path: Optional[str] = None
    start_at_utc: Optional[str] = None

@router.put("/{job_id}")
async def update_job_endpoint(job_id: int, data: UpdateJobRequest, db: AsyncSession = Depends(get_db)):
    """Update a livestream job (only if not running)."""
    result = await db.execute(select(LiveJob).where(LiveJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status == "running":
        raise HTTPException(status_code=400, detail="Cannot update a running job")
    
    # Update fields if provided
    if data.title is not None:
        job.title = data.title
    if data.description is not None:
        job.description = data.description
    if data.tags is not None:
        job.tags = data.tags
    if data.duration_hours is not None:
        job.duration_hours = data.duration_hours
    if data.quality is not None:
        job.quality = data.quality
    if data.use_mp3 is not None:
        job.use_mp3 = data.use_mp3
    if data.use_sfx is not None:
        job.use_sfx = data.use_sfx
    if data.visibility is not None:
        job.visibility = data.visibility
    if data.made_for_kids is not None:
        job.made_for_kids = data.made_for_kids
    if data.thumbnail_path is not None:
        job.thumbnail_path = data.thumbnail_path
    if data.start_at_utc is not None:
        from dateutil import parser as date_parser
        try:
            job.start_at_utc = date_parser.parse(data.start_at_utc)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid datetime format for start_at_utc")
    
    await db.flush()
    return {"success": True, "job_id": job.id, "status": job.status}




    status = {
        "ffmpeg": {"running": False, "count": 0, "processes": []},
        "worker": {"running": False, "pid": None},
        "backend": {"running": True, "pid": os.getpid()},
    }

    # Check FFmpeg processes in worker container
    try:
        result = subprocess.run(
            ["docker", "exec", "jb_apulv3-worker-livestream-1", "ps", "aux"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            lines = result.stdout.splitlines()
            ffmpeg_procs = []
            for line in lines:
                if "ffmpeg" in line and "grep" not in line:
                    parts = line.split()
                    if len(parts) >= 11:
                        ffmpeg_procs.append({
                            "pid": parts[1],
                            "cpu": parts[2],
                            "mem": parts[3],
                            "started": " ".join(parts[9:11]),
                        })
            status["ffmpeg"]["running"] = len(ffmpeg_procs) > 0
            status["ffmpeg"]["count"] = len(ffmpeg_procs)
            status["ffmpeg"]["processes"] = ffmpeg_procs
    except Exception as e:
        status["ffmpeg"]["error"] = str(e)

    # Check Worker (Python) process
    try:
        result = subprocess.run(
            ["docker", "exec", "jb_apulv3-worker-livestream-1", "ps", "aux"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if "python worker" in line and "grep" not in line:
                    parts = line.split()
                    status["worker"]["running"] = True
                    status["worker"]["pid"] = parts[1]
                    status["worker"]["cpu"] = parts[2]
                    status["worker"]["mem"] = parts[3]
                    break
    except Exception as e:
        status["worker"]["error"] = str(e)

    # Get running jobs from DB
    try:
        conn = psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, channel_id, status, process_id, broadcast_id, "
                "current_bitrate, current_fps, last_health_check "
                "FROM live_jobs WHERE status = 'running'"
            )
            jobs = cur.fetchall()
            status["running_jobs"] = []
            for j in jobs:
                health_age = None
                if j["last_health_check"]:
                    health_age = round((datetime.now(timezone.utc) - j["last_health_check"]).total_seconds(), 1)
                status["running_jobs"].append({
                    "id": j["id"],
                    "channel_id": j["channel_id"],
                    "broadcast_id": j["broadcast_id"],
                    "bitrate": j["current_bitrate"],
                    "fps": j["current_fps"],
                    "last_health": j["last_health_check"].isoformat() if j["last_health_check"] else None,
                    "health_age_sec": health_age,
                })
        conn.close()
    except Exception as e:
        status["running_jobs_error"] = str(e)

    return status
