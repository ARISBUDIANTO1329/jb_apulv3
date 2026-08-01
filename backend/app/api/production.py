from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func, text
from pydantic import BaseModel
from typing import Optional
import subprocess
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.db.session import get_db
from app.models.production import ProductionJob
from app.models.channel import Channel
from app.models.media import MediaItem
from app.models.asset_log import AssetUsageLog
from app.services.storage import storage

router = APIRouter()


def hms_to_seconds(value: str) -> int:
    """Convert HH:MM:SS string to seconds. Returns 0 if invalid."""
    import re
    if not re.match(r'^\d{2}:\d{2}:\d{2}$', str(value)):
        return 0
    try:
        parts = str(value).split(':')
        h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
        return (h * 3600) + (m * 60) + s
    except (ValueError, IndexError):
        return 0


class ProductionRequest(BaseModel):
    channel_id: int
    production_method: str = "ready_video"  # ready_video, raw_video_auto_seamless, merge_video
    video_source: Optional[str] = None
    num_songs: int = 1
    no_mp3: bool = False
    no_sfx: bool = False
    sfx_file: Optional[str] = None
    intro_file: Optional[str] = None
    mp3_file: Optional[str] = None
    mp3_mode: str = "shuffle"  # shuffle, single
    duration_mode: str = "mp3"  # mp3, manual
    custom_duration: Optional[str] = None  # HH:MM:SS format
    production_mode: str = "v2"
    # Static video options
    tail_length: int = 3  # 1-5 seconds
    slowmo_percent: int = 0  # 0, 10, 20, 30, 40, 50
    # Dynamic merge options
    merge_count: int = 10
    merge_resolution: str = "1920x1080"
    merge_transition_enabled: bool = True
    merge_transition_name: str = "fade"
    merge_transition_duration: float = 1.0
    merge_speed: float = 1.0
    dynamic_output_count: int = 1
    # Start All mode
    start_all: bool = False


@router.get("")
async def list_jobs(
    channel_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    method: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List production jobs."""
    query = select(ProductionJob)
    if channel_id:
        query = query.where(ProductionJob.channel_id == channel_id)
    if status:
        query = query.where(ProductionJob.status == status)
    if method:
        query = query.where(ProductionJob.production_method == method)
    query = query.order_by(ProductionJob.created_at.desc())
    result = await db.execute(query)
    jobs = result.scalars().all()

    return [{
        "id": job.id,
        "channel_id": job.channel_id,
        "video_source": job.video_source,
        "output_filename": job.output_filename,
        "status": job.status,
        "progress": job.progress,
        "audio_status": job.audio_status,
        "video_status": job.video_status,
        "final_status": job.final_status,
        "production_method": job.production_method,
        "error_message": job.error_message,
        "process_status": job.process_status,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    } for job in jobs]


@router.get("/cooldown/{channel_id}")
async def get_cooldown_videos(channel_id: int, db: AsyncSession = Depends(get_db)):
    """Get videos that are on cooldown for a channel."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    result = await db.execute(
        select(AssetUsageLog)
        .where(AssetUsageLog.channel_id == channel_id)
        .where(AssetUsageLog.usage_type == "upload_regular")
        .where(AssetUsageLog.usage_date >= cutoff)
        .order_by(AssetUsageLog.usage_date.desc())
    )
    logs = result.scalars().all()

    cooldown_map = {}
    for log in logs:
        key = log.asset_key or log.file_path
        if key not in cooldown_map:
            cooldown_map[key] = {
                "asset_key": key,
                "asset_filename": log.asset_filename,
                "usage_date": log.usage_date.isoformat() if log.usage_date else None,
                "cooldown_until": log.cooldown_until.isoformat() if log.cooldown_until else None,
            }

    return {"channel_id": channel_id, "cooldown_videos": list(cooldown_map.values())}


@router.post("")
async def create_job(data: ProductionRequest, db: AsyncSession = Depends(get_db)):
    """Create a production job (supports all 3 modes + start_all)."""
    # Verify channel
    result = await db.execute(select(Channel).where(Channel.id == data.channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    method = data.production_method
    if method not in ("ready_video", "raw_video_auto_seamless", "merge_video"):
        raise HTTPException(status_code=400, detail="Invalid production_method")

    # Start All mode: batch all available videos not on cooldown
    if data.start_all and method != "merge_video":
        return await _start_all_jobs(data, db)

    video_source = data.video_source

    # For random pick (no video_source specified, ready_video mode)
    if not video_source and method == "ready_video":
        video_source = await _pick_random_available(data.channel_id, "video", db)
        if not video_source:
            raise HTTPException(status_code=400, detail="No available video found (all on cooldown or empty)")
    elif not video_source and method == "raw_video_auto_seamless":
        video_source = await _pick_random_available(data.channel_id, "video-raw", db)
        if not video_source:
            raise HTTPException(status_code=400, detail="No available raw video found")

    # Generate output filename: final_ + original source name
    from pathlib import Path as _Path
    source_stem = _Path(video_source).stem if video_source else "video"
    source_ext = _Path(video_source).suffix if video_source else ".mp4"
    output_filename = f"final_{source_stem}{source_ext}"

    # Create job
    # Convert custom_duration from HH:MM:SS to seconds
    custom_dur_seconds = hms_to_seconds(data.custom_duration) if data.custom_duration else None

    job = ProductionJob(
        channel_id=data.channel_id,
        video_source=video_source,
        num_songs=data.num_songs,
        no_mp3=data.no_mp3,
        no_sfx=data.no_sfx,
        sfx_file=data.sfx_file,
        intro_file=data.intro_file,
        mp3_file=data.mp3_file,
        mp3_mode=data.mp3_mode,
        duration_mode=data.duration_mode,
        custom_duration=custom_dur_seconds,
        production_mode=data.production_mode,
        production_method=method,
        tail_length=data.tail_length,
        slowmo_percent=data.slowmo_percent,
        merge_count=data.merge_count,
        merge_resolution=data.merge_resolution,
        merge_transition_enabled=data.merge_transition_enabled,
        merge_transition_name=data.merge_transition_name,
        merge_transition_duration=data.merge_transition_duration,
        merge_speed=data.merge_speed,
        dynamic_output_count=data.dynamic_output_count,
        output_filename=output_filename,
        status="pending",
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)

    return {
        "success": True,
        "job_id": job.id,
        "production_method": method,
        "status": "pending",
        "message": f"Production job created ({method}). Worker will pick it up.",
    }


@router.post("/batch")
async def create_batch_jobs(data: ProductionRequest, db: AsyncSession = Depends(get_db)):
    """Create multiple production jobs at once (for start_all mode)."""
    result = await db.execute(select(Channel).where(Channel.id == data.channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    method = data.production_method
    if method not in ("ready_video", "raw_video_auto_seamless"):
        raise HTTPException(status_code=400, detail="Batch only supports ready_video and raw_video_auto_seamless")

    asset_type = "video-raw" if method == "raw_video_auto_seamless" else "video"
    media_query = select(MediaItem).where(
        MediaItem.channel_id == data.channel_id,
        MediaItem.asset_type == asset_type,
    )
    media_result = await db.execute(media_query)
    media_items = media_result.scalars().all()

    if not media_items:
        raise HTTPException(status_code=400, detail=f"No {asset_type} files found for this channel")

    import secrets
    from datetime import datetime, timezone

    created = 0
    custom_dur_seconds = hms_to_seconds(data.custom_duration) if data.custom_duration else None
    for item in media_items:
        source_stem = Path(item.filename).stem
        source_ext = Path(item.filename).suffix or ".mp4"
        output_filename = f"final_{source_stem}{source_ext}"

        job = ProductionJob(
            channel_id=data.channel_id,
            video_source=item.filename,
            num_songs=data.num_songs,
            no_mp3=data.no_mp3,
            no_sfx=data.no_sfx,
            sfx_file=data.sfx_file,
            intro_file=data.intro_file,
            mp3_file=data.mp3_file,
            mp3_mode=data.mp3_mode,
            duration_mode=data.duration_mode,
            custom_duration=custom_dur_seconds,
            production_mode=data.production_mode,
            production_method=method,
            tail_length=data.tail_length,
            slowmo_percent=data.slowmo_percent,
            output_filename=output_filename,
            status="pending",
        )
        db.add(job)
        created += 1

    await db.flush()

    return {
        "success": True,
        "created": created,
        "production_method": method,
        "message": f"Batch: {created} jobs created ({method}).",
    }


@router.get("/runtime")
async def get_runtime_status(channel_id: Optional[int] = Query(None)):
    """Check production runtime status (processes running)."""
    status = {
        "orchestrator": False,
        "auto_seamless": False,
        "ffmpeg": False,
        "lines": [],
    }

    try:
        result = subprocess.run(
            ["ps", "-eo", "pid,etimes,cmd"],
            capture_output=True, text=True, timeout=5,
        )
        lines = (result.stdout or "").splitlines()
        for line in lines:
            if "production" in line.lower() or "ffmpeg" in line.lower() or "merge_video" in line.lower():
                if "grep" not in line:
                    status["lines"].append(line.strip())
                    if "worker" in line.lower() or "orchestrator" in line.lower():
                        status["orchestrator"] = True
                    if "ffmpeg" in line.lower():
                        status["ffmpeg"] = True
    except Exception:
        pass

    # Get worker log tail
    log_path = Path("/app/storage/logs/production_worker.log")
    log_lines = []
    if log_path.exists():
        try:
            with open(log_path, "r") as f:
                all_lines = f.readlines()
                log_lines = [l.rstrip() for l in all_lines[-40:]]
        except Exception:
            pass

    return {**status, "worker_log": log_lines}


@router.get("/{job_id}")
async def get_job(job_id: int, db: AsyncSession = Depends(get_db)):
    """Get production job details."""
    result = await db.execute(select(ProductionJob).where(ProductionJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "id": job.id,
        "channel_id": job.channel_id,
        "video_source": job.video_source,
        "output_filename": job.output_filename,
        "status": job.status,
        "progress": job.progress,
        "audio_status": job.audio_status,
        "video_status": job.video_status,
        "final_status": job.final_status,
        "production_method": job.production_method,
        "audio_path": job.audio_path,
        "video_path": job.video_path,
        "final_path": job.final_path,
        "error_message": job.error_message,
        "process_status": job.process_status,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


@router.post("/{job_id}/send-upload-ready")
async def send_to_upload_ready(job_id: int, db: AsyncSession = Depends(get_db)):
    """Move finished production output to upload_ready folder."""
    result = await db.execute(select(ProductionJob).where(ProductionJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.final_status != "done" or not job.final_path:
        raise HTTPException(status_code=400, detail="Production job not finished")

    source_path = Path(job.final_path)
    if not source_path.exists():
        raise HTTPException(status_code=400, detail="Final file not found on disk")

    # Check if already in upload_ready
    existing = await db.execute(
        select(MediaItem).where(
            MediaItem.channel_id == job.channel_id,
            MediaItem.asset_type == "upload_ready",
            MediaItem.filename == (job.output_filename or source_path.name),
        )
    )
    existing_record = existing.scalar_one_or_none()
    if existing_record:
        # File already in upload_ready (created by final_renderer), but ensure cooldown log exists
        cooldown_exists = await db.execute(
            select(AssetUsageLog).where(
                AssetUsageLog.channel_id == job.channel_id,
                AssetUsageLog.file_path == str(source_path),
                AssetUsageLog.usage_type == "upload_regular",
            )
        )
        if not cooldown_exists.scalar_one_or_none():
            log = AssetUsageLog(
                channel_id=job.channel_id,
                asset_key=f"assets/video/{job.channel_id}/{job.video_source}",
                asset_filename=job.video_source,
                file_path=str(source_path),
                asset_type="video",
                usage_type="upload_regular",
                used_for="production",
                cooldown_until=datetime.now(timezone.utc) + timedelta(days=30),
            )
            db.add(log)
            await db.flush()
        return {"success": True, "message": "File already in upload_ready", "media_id": existing_record.id}

    # Copy to upload_ready
    upload_ready_dir = storage.get_upload_ready_path(job.channel_id)
    dest = upload_ready_dir / (job.output_filename or source_path.name)
    if str(source_path) != str(dest):
        shutil.copy2(str(source_path), str(dest))

    # Create media record
    media = MediaItem(
        channel_id=job.channel_id,
        filename=job.output_filename or source_path.name,
        file_path=str(dest),
        asset_type="upload_ready",
        file_size=dest.stat().st_size,
    )
    db.add(media)

    # Log usage
    log = AssetUsageLog(
        channel_id=job.channel_id,
        asset_key=f"assets/video/{job.channel_id}/{job.video_source}",
        asset_filename=job.video_source,
        file_path=str(source_path),
        asset_type="video",
        usage_type="upload_regular",
        used_for="production",
        cooldown_until=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.add(log)
    await db.flush()

    return {"success": True, "message": "File sent to upload_ready", "media_id": media.id}


@router.delete("/{job_id}")
async def delete_job(job_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a production job."""
    result = await db.execute(select(ProductionJob).where(ProductionJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.final_path:
        storage.delete_file(job.final_path)

    await db.delete(job)
    return {"success": True}


@router.post("/{job_id}/retry")
async def retry_job(job_id: int, db: AsyncSession = Depends(get_db)):
    """Retry a failed production job by resetting its status to pending."""
    result = await db.execute(select(ProductionJob).where(ProductionJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("failed", "error"):
        raise HTTPException(status_code=400, detail="Only failed jobs can be retried")

    # Reset job status for worker to pick up
    job.status = "pending"
    job.progress = 0
    job.audio_status = "pending"
    job.video_status = "pending"
    job.final_status = "pending"
    job.error_message = None
    job.process_status = "retry"
    job.audio_path = None
    job.video_path = None
    job.final_path = None
    await db.flush()

    return {"success": True, "message": f"Job #{job_id} reset to pending. Worker akan memproses ulang."}


@router.delete("/batch/{method}")
async def delete_all_jobs(method: str, channel_id: int = Query(...), db: AsyncSession = Depends(get_db)):
    """Delete all jobs for a channel by method (final or dynamic)."""
    if method not in ("final", "dynamic"):
        raise HTTPException(status_code=400, detail="Method must be 'final' or 'dynamic'")

    query = select(ProductionJob).where(ProductionJob.channel_id == channel_id)
    if method == "dynamic":
        query = query.where(ProductionJob.video_source.like("dynamic_merge_%"))
    else:
        query = query.where(
            (ProductionJob.video_source == None) |  # noqa: E711
            (~ProductionJob.video_source.like("dynamic_merge_%"))
        )

    result = await db.execute(query)
    jobs = result.scalars().all()

    for job in jobs:
        if job.final_path:
            storage.delete_file(job.final_path)
        await db.delete(job)

    await db.flush()
    return {"success": True, "deleted": len(jobs), "method": method}


# ── Helpers ──────────────────────────────────────────────────────


async def _pick_random_available(channel_id: int, asset_type: str, db: AsyncSession) -> Optional[str]:
    """Pick a random video that is NOT on cooldown."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    # Get cooldown paths
    cooldown_result = await db.execute(
        select(AssetUsageLog.asset_key)
        .where(AssetUsageLog.channel_id == channel_id)
        .where(AssetUsageLog.usage_type == "upload_regular")
        .where(AssetUsageLog.usage_date >= cutoff)
    )
    cooldown_keys = {row[0] for row in cooldown_result.all() if row[0]}

    # Get all media of this type
    media_result = await db.execute(
        select(MediaItem)
        .where(MediaItem.channel_id == channel_id)
        .where(MediaItem.asset_type == asset_type)
    )
    items = media_result.scalars().all()

    # Filter out cooldown
    available = []
    for item in items:
        key = f"assets/{asset_type}/{channel_id}/{item.filename}"
        if key not in cooldown_keys:
            available.append(item)

    if not available:
        return None

    # Pick random
    import random
    chosen = random.choice(available)
    return chosen.filename


async def _start_all_jobs(data: ProductionRequest, db: AsyncSession):
    """Batch all videos not on cooldown."""
    method = data.production_method
    asset_type = "video-raw" if method == "raw_video_auto_seamless" else "video"

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    cooldown_result = await db.execute(
        select(AssetUsageLog.asset_key)
        .where(AssetUsageLog.channel_id == data.channel_id)
        .where(AssetUsageLog.usage_type == "upload_regular")
        .where(AssetUsageLog.usage_date >= cutoff)
    )
    cooldown_keys = {row[0] for row in cooldown_result.all() if row[0]}

    media_result = await db.execute(
        select(MediaItem)
        .where(MediaItem.channel_id == data.channel_id)
        .where(MediaItem.asset_type == asset_type)
    )
    items = media_result.scalars().all()

    created = 0
    for item in items:
        key = f"assets/{asset_type}/{data.channel_id}/{item.filename}"
        if key in cooldown_keys:
            continue

        job = ProductionJob(
            channel_id=data.channel_id,
            video_source=item.filename,
            num_songs=data.num_songs,
            no_mp3=data.no_mp3,
            no_sfx=data.no_sfx,
            sfx_file=data.sfx_file,
            intro_file=data.intro_file,
            mp3_file=data.mp3_file,
            mp3_mode=data.mp3_mode,
            duration_mode=data.duration_mode,
            custom_duration=custom_dur_seconds,
            production_mode=data.production_mode,
            production_method=method,
            tail_length=data.tail_length,
            slowmo_percent=data.slowmo_percent,
            status="pending",
        )
        db.add(job)
        created += 1

    await db.flush()

    return {
        "success": True,
        "created": created,
        "production_method": method,
        "message": f"Start All: {created} jobs created ({method}). Videos on cooldown were skipped.",
    }


# ── Additional Endpoints ──────────────────────────────────────────


@router.get("/media/{channel_id}")
async def get_available_media(
    channel_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get available media files for production forms (video, video-raw, mp3, sfx, intro)."""
    result = await db.execute(
        select(MediaItem)
        .where(MediaItem.channel_id == channel_id)
        .where(MediaItem.asset_type.in_(["video", "video-raw", "mp3", "sfx", "intro"]))
        .order_by(MediaItem.asset_type, MediaItem.filename)
    )
    items = result.scalars().all()

    grouped = {"video": [], "video-raw": [], "mp3": [], "sfx": [], "intro": []}
    for item in items:
        if item.asset_type in grouped:
            grouped[item.asset_type].append({
                "id": item.id,
                "filename": item.filename,
                "original_name": item.original_name or item.filename,
                "file_size": item.file_size or 0,
            })

    return grouped


@router.get("/preview/{job_id}")
async def preview_job(job_id: int, db: AsyncSession = Depends(get_db)):
    """Stream a finished production job video for preview."""
    result = await db.execute(select(ProductionJob).where(ProductionJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.final_path:
        raise HTTPException(status_code=404, detail="No final file for this job")

    file_path = Path(job.final_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        path=str(file_path),
        media_type="video/mp4",
        filename=job.output_filename or file_path.name,
    )


@router.get("/logs")
async def get_logs():
    """Get production worker logs."""
    log_path = Path("/app/storage/logs/production_worker.log")
    log_lines = []
    if log_path.exists():
        try:
            with open(log_path, "r") as f:
                all_lines = f.readlines()
                log_lines = [l.rstrip() for l in all_lines[-50:]]
        except Exception:
            pass
    return {"lines": log_lines}


# ── New Endpoints (synced from v2) ──────────────────────────────────


@router.post("/select-method")
async def select_method(data: dict):
    """Persist selected production method (no-op in API, client uses localStorage)."""
    method = data.get("production_method", "ready_video")
    return {"ok": True, "production_method": method}


@router.get("/dynamic-status/{channel_id}")
async def get_dynamic_status(channel_id: int):
    """Get dynamic video live status from JSON file."""
    status_path = Path(f"/app/storage/app/dynamic_status/channel_{channel_id}.json")
    default = {
        "status": "idle",
        "progress": 0,
        "message": "Belum ada proses Dynamic berjalan.",
        "channel_id": channel_id,
        "output_count": 0,
        "current_output": 0,
        "video_per_merge": 0,
        "stage": "idle",
        "output_file": None,
        "size_bytes": 0,
        "started_at": None,
        "updated_at": None,
        "elapsed_seconds": 0,
    }
    if status_path.exists():
        try:
            import json
            with open(status_path, "r") as f:
                data = json.load(f)
            default.update(data)
            # Calculate elapsed
            if default.get("started_at"):
                from datetime import datetime
                started = datetime.fromisoformat(default["started_at"])
                default["elapsed_seconds"] = max(0, int((datetime.now() - started).total_seconds()))
        except Exception:
            pass
    return default


@router.get("/seamless-progress/{channel_id}")
async def get_seamless_progress(channel_id: int, db: AsyncSession = Depends(get_db)):
    """Get seamless (static video) progress for a channel."""
    from app.models.auto_seamless_progress import AutoSeamlessProgress

    # Active items
    active_result = await db.execute(
        select(AutoSeamlessProgress)
        .where(AutoSeamlessProgress.channel_id == channel_id)
        .where(AutoSeamlessProgress.status.in_(["pending", "processing"]))
        .order_by(AutoSeamlessProgress.id.desc())
        .limit(10)
    )
    active_items = active_result.scalars().all()

    # Success count (seamless videos created)
    from sqlalchemy import func as sqlfunc
    success_result = await db.execute(
        select(sqlfunc.count(MediaItem.id))
        .where(MediaItem.channel_id == channel_id)
        .where(MediaItem.asset_type == "video")
        .where(MediaItem.filename.like("final_raw_%"))
    )
    success_count = success_result.scalar() or 0

    # Failed count
    failed_result = await db.execute(
        select(sqlfunc.count(AutoSeamlessProgress.id))
        .where(AutoSeamlessProgress.channel_id == channel_id)
        .where(AutoSeamlessProgress.status == "failed")
    )
    failed_count = failed_result.scalar() or 0

    # Recent seamless outputs
    recent_result = await db.execute(
        select(MediaItem)
        .where(MediaItem.channel_id == channel_id)
        .where(MediaItem.asset_type == "video")
        .where(MediaItem.filename.like("final_raw_%"))
        .order_by(MediaItem.id.desc())
        .limit(10)
    )
    recent_items = recent_result.scalars().all()

    return {
        "active": [{
            "id": item.id,
            "raw_filename": item.raw_filename,
            "progress": item.progress,
            "status": item.status,
            "message": item.message,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        } for item in active_items],
        "active_count": len(active_items),
        "success_count": success_count,
        "failed_count": failed_count,
        "recent": [{
            "id": item.id,
            "filename": item.filename,
            "original_name": item.original_name or item.filename,
            "file_size": item.file_size or 0,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        } for item in recent_items],
    }


@router.get("/system-logs/{mode}")
async def get_system_logs(mode: str, channel_id: int = Query(...), db: AsyncSession = Depends(get_db)):
    """Get system logs per production mode (final, static, dynamic).
    Reads real-time logs from process_log JSONB column."""
    if mode not in ("final", "static", "dynamic"):
        raise HTTPException(status_code=400, detail="Mode must be final, static, or dynamic")

    lines = []

    # Get recent jobs for this channel
    result = await db.execute(
        select(ProductionJob)
        .where(ProductionJob.channel_id == channel_id)
        .order_by(ProductionJob.id.desc())
        .limit(10)
    )
    jobs = result.scalars().all()

    if not jobs:
        return {"mode": mode, "lines": ["Belum ada production job."]}

    # Find the most recent active job (processing/pending), or fallback to latest
    active_job = None
    for job in jobs:
        if job.status in ("processing", "pending") and job.final_status != "done":
            active_job = job
            break
    if not active_job:
        active_job = jobs[0]

    # Summary header
    done_count = sum(1 for j in jobs if j.final_status == "done")
    running_count = sum(1 for j in jobs if j.final_status != "done" and j.status not in ("failed", "error"))
    lines.append(f"[{mode.upper()}] Channel ID: {channel_id}")
    lines.append(f"[{mode.upper()}] Jobs: {len(jobs)} | Done: {done_count} | Running: {running_count}")
    lines.append(f"[{mode.upper()}] Active Job #{active_job.id}: progress={active_job.progress or 0}% | {active_job.process_status or 'waiting'}")
    lines.append("")

    # Read process_log JSONB from the active job
    process_log = active_job.process_log or []
    if isinstance(process_log, str):
        import json
        try:
            process_log = json.loads(process_log)
        except Exception:
            process_log = []

    if process_log:
        lines.append("--- Real-time Log ---")
        for entry in process_log:
            ts = entry.get("t", "??:??:??")
            msg = entry.get("m", "")
            lines.append(f"[{ts}] {msg}")
    else:
        lines.append("No logs yet. Waiting for job to start...")

    return {"mode": mode, "lines": lines, "job_id": active_job.id, "progress": active_job.progress or 0, "status": active_job.process_status or ""}


@router.post("/auto-schedule")
async def store_auto_schedule(data: dict, db: AsyncSession = Depends(get_db)):
    """Create or update auto-production schedule."""
    from app.models.auto_production_schedule import AutoProductionSchedule
    from app.models.auto_control_room_job import AutoControlRoomJob, AutoControlRoomJobItem
    from datetime import datetime, timedelta

    channel_id = data.get("channel_id")
    target = data.get("target", "upload_regular")
    workflow = data.get("workflow", "static")
    schedule_time = data.get("schedule_time", "09:00")
    start_mode = data.get("start_mode", "today")
    config = data.get("config", {})

    if not channel_id:
        raise HTTPException(status_code=400, detail="Channel ID required")

    # Calculate next run time
    now = datetime.now()
    hour, minute = map(int, schedule_time.split(":")[:2])
    if start_mode == "today":
        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
    else:
        next_run = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)

    # Find or create schedule
    result = await db.execute(
        select(AutoProductionSchedule)
        .where(AutoProductionSchedule.channel_id == channel_id)
        .where(AutoProductionSchedule.target == target)
        .where(AutoProductionSchedule.workflow == workflow)
    )
    schedule = result.scalar_one_or_none()

    if schedule:
        schedule.schedule_time = f"{schedule_time}:00"
        schedule.start_mode = start_mode
        schedule.is_active = True
        schedule.config_json = config
        if target != "production_daily":
            schedule.next_run_at = next_run
    else:
        schedule = AutoProductionSchedule(
            channel_id=channel_id,
            target=target,
            workflow=workflow,
            schedule_time=f"{schedule_time}:00",
            start_mode=start_mode,
            is_active=True,
            config_json=config,
            next_run_at=next_run,
        )
        db.add(schedule)

    await db.flush()
    await db.refresh(schedule)

    # Create control room job if not production_daily
    control_room_job = None
    if target != "production_daily":
        result = await db.execute(
            select(AutoControlRoomJob)
            .where(AutoControlRoomJob.auto_production_schedule_id == schedule.id)
            .where(AutoControlRoomJob.status.in_(["waiting", "blocked"]))
            .order_by(AutoControlRoomJob.id.desc())
        )
        control_room_job = result.scalar_one_or_none()

        batch_count = max(1, min(50, int(config.get("production_batch_count", config.get("daily_production_count", 1)))))

        if not control_room_job:
            control_room_job = AutoControlRoomJob(
                auto_production_schedule_id=schedule.id,
                channel_id=channel_id,
                target=target,
                workflow=workflow,
                run_date=now.strftime("%Y-%m-%d"),
                status="waiting",
                current_stage="pending_activation",
                progress=0,
                total_items=batch_count,
                done_items=0,
                config_json=config,
            )
            db.add(control_room_job)
        else:
            control_room_job.channel_id = channel_id
            control_room_job.target = target
            control_room_job.workflow = workflow
            control_room_job.status = "waiting"
            control_room_job.current_stage = "pending_activation"
            control_room_job.progress = 0
            control_room_job.total_items = batch_count
            control_room_job.done_items = 0
            control_room_job.config_json = config
            control_room_job.error_message = None

        await db.flush()
        await db.refresh(control_room_job)

        # Create job items
        # Delete existing items first
        await db.execute(
            delete(AutoControlRoomJobItem).where(
                AutoControlRoomJobItem.auto_control_room_job_id == control_room_job.id
            )
        )

        for i in range(1, batch_count + 1):
            source_type = "upload_source_pending"
            if target == "livestream":
                source_type = "livestream_source_pending"
            elif target == "production_daily":
                source_type = "production_source_pending"

            item = AutoControlRoomJobItem(
                auto_control_room_job_id=control_room_job.id,
                queue_order=i,
                target=target,
                workflow=workflow,
                source_type=source_type,
                status="waiting",
                current_stage="waiting",
                progress=0,
            )
            db.add(item)

        await db.flush()

    return {
        "ok": True,
        "message": "Setup berhasil disimpan ke Control Room.",
        "schedule_id": schedule.id,
        "control_room_job_id": control_room_job.id if control_room_job else None,
        "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None,
    }


@router.get("/auto-schedule/{channel_id}")
async def get_auto_schedule(channel_id: int, db: AsyncSession = Depends(get_db)):
    """Get active auto-production schedule for a channel."""
    from app.models.auto_production_schedule import AutoProductionSchedule
    from app.models.auto_control_room_job import AutoControlRoomJob

    result = await db.execute(
        select(AutoProductionSchedule)
        .where(AutoProductionSchedule.channel_id == channel_id)
        .where(AutoProductionSchedule.target == "upload_regular")
        .where(AutoProductionSchedule.is_active == True)  # noqa: E712
        .order_by(AutoProductionSchedule.id.desc())
    )
    schedule = result.scalar_one_or_none()

    control_job = None
    if schedule:
        result = await db.execute(
            select(AutoControlRoomJob)
            .where(AutoControlRoomJob.auto_production_schedule_id == schedule.id)
            .order_by(AutoControlRoomJob.id.desc())
        )
        control_job = result.scalar_one_or_none()

    return {
        "schedule": {
            "id": schedule.id,
            "target": schedule.target,
            "workflow": schedule.workflow,
            "schedule_time": schedule.schedule_time,
            "start_mode": schedule.start_mode,
            "config": schedule.config_json,
            "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None,
        } if schedule else None,
        "control_job": {
            "id": control_job.id,
            "status": control_job.status,
            "current_stage": control_job.current_stage,
            "progress": control_job.progress,
            "total_items": control_job.total_items,
            "done_items": control_job.done_items,
        } if control_job else None,
    }
