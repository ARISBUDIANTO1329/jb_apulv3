import shutil
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime, timezone

from app.db.session import get_db
from app.models.channel import Channel
from app.models.media import MediaItem
from app.models.production import ProductionJob
from app.models.upload import UploadBatch, UploadBatchItem
from app.models.livestream import LiveJob
from app.models.pipeline import Pipeline, PipelineRun
from app.models.asset_log import AssetUsageLog
from app.services.storage import storage

router = APIRouter()


class ChannelCreate(BaseModel):
    name: str
    youtube_channel_id: Optional[str] = None
    youtube_channel_url: Optional[str] = None
    niche: Optional[str] = None
    email: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None


class ChannelUpdate(BaseModel):
    name: Optional[str] = None
    youtube_channel_id: Optional[str] = None
    youtube_channel_url: Optional[str] = None
    niche: Optional[str] = None
    email: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    stream_key: Optional[str] = None
    proxy_host: Optional[str] = None
    proxy_port: Optional[int] = None
    proxy_type: Optional[str] = None
    chrome_profile: Optional[str] = None
    monetization_status: Optional[str] = None
    monetization_notes: Optional[str] = None


class ChannelResponse(BaseModel):
    id: int
    name: str
    youtube_channel_id: Optional[str]
    youtube_channel_url: Optional[str]
    status: str
    niche: Optional[str]
    email: Optional[str]
    stream_key: Optional[str]
    subscriber_count: int
    total_views: int
    video_count: int
    proxy_host: Optional[str]
    proxy_port: Optional[int]
    proxy_type: Optional[str]
    chrome_profile: Optional[str]
    last_upload: Optional[datetime] = None
    last_livestream: Optional[datetime] = None
    access_token: Optional[str] = None

    token_status: Optional[str] = None
    token_error: Optional[str] = None
    token_expires_at: Optional[datetime] = None
    token_checked_at: Optional[datetime] = None
    monetization_status: Optional[str] = None
    monetization_date: Optional[datetime] = None
    monetization_notes: Optional[str] = None
model_config = ConfigDict(from_attributes=True, json_encoders={datetime: lambda v: v.isoformat() if v else None})


async def _get_last_activity(db: AsyncSession, channel_id: int):
    """Get last upload and livestream timestamps from related tables."""
    # Last successful upload
    upload_q = await db.execute(
        select(func.max(UploadBatchItem.finished_at))
        .where(UploadBatchItem.channel_id == channel_id)
        .where(UploadBatchItem.status == "done")
    )
    last_upload = upload_q.scalar()

    # Fallback: use created_at if finished_at is null
    if not last_upload:
        upload_q2 = await db.execute(
            select(func.max(UploadBatchItem.created_at))
            .where(UploadBatchItem.channel_id == channel_id)
            .where(UploadBatchItem.status == "done")
        )
        last_upload = upload_q2.scalar()

    # Last livestream (any that was started)
    live_q = await db.execute(
        select(func.max(LiveJob.started_at))
        .where(LiveJob.channel_id == channel_id)
        .where(LiveJob.status.in_(["running", "finished", "stopped"]))
    )
    last_livestream = live_q.scalar()

    # Fallback: use created_at if started_at is null
    if not last_livestream:
        live_q2 = await db.execute(
            select(func.max(LiveJob.created_at))
            .where(LiveJob.channel_id == channel_id)
            .where(LiveJob.status.in_(["running", "finished", "stopped"]))
        )
        last_livestream = live_q2.scalar()

    return last_upload, last_livestream


@router.get("", response_model=list[ChannelResponse])
async def list_channels(db: AsyncSession = Depends(get_db)):
    """List all channels with auto-computed last activity."""
    result = await db.execute(select(Channel).order_by(Channel.name))
    channels = result.scalars().all()

    response = []
    for ch in channels:
        # Auto-compute from related tables
        last_upload, last_livestream = await _get_last_activity(db, ch.id)

        # Sync back to channel table (best-effort, no error if fails)
        try:
            if last_upload and (not ch.last_upload or last_upload > ch.last_upload):
                ch.last_upload = last_upload
            if last_livestream and (not ch.last_livestream or last_livestream > ch.last_livestream):
                ch.last_livestream = last_livestream
        except Exception:
            pass

        ch_dict = {
            "id": ch.id,
            "name": ch.name,
            "youtube_channel_id": ch.youtube_channel_id,
            "youtube_channel_url": ch.youtube_channel_url,
            "status": ch.status,
            "niche": ch.niche,
            "email": ch.email,
            "stream_key": ch.stream_key,
            "subscriber_count": ch.subscriber_count,
            "total_views": ch.total_views,
            "video_count": ch.video_count,
            "proxy_host": ch.proxy_host,
            "proxy_port": ch.proxy_port,
            "proxy_type": ch.proxy_type,
            "chrome_profile": ch.chrome_profile,
            "last_upload": last_upload.isoformat() if last_upload else None,
            "last_livestream": last_livestream.isoformat() if last_livestream else None,
            "access_token": ch.access_token,
            "token_status": ch.token_status,
            "token_error": ch.token_error,
            "token_expires_at": ch.token_expires_at.isoformat() if ch.token_expires_at else None,
            "token_checked_at": ch.token_checked_at.isoformat() if ch.token_checked_at else None,
            "monetization_status": ch.monetization_status or "not_monetized",
            "monetization_date": ch.monetization_date.isoformat() if ch.monetization_date else None,
            "monetization_notes": ch.monetization_notes,
        }
        response.append(ch_dict)

    try:
        await db.commit()
    except Exception:
        pass

    return response


@router.get("/token-health")
async def get_token_health(db: AsyncSession = Depends(get_db)):
    """Check token health for all channels."""
    from datetime import timedelta
    result = await db.execute(select(Channel))
    channels = result.scalars().all()

    health = []
    for ch in channels:
        status = "unknown"
        message = None
        needs_reconnect = False

        if not ch.access_token and not ch.refresh_token:
            status = "not_connected"
            message = "Channel belum terkoneksi ke Google"
            needs_reconnect = True
        elif ch.token_status == "error":
            status = "error"
            message = ch.token_error or "Token refresh gagal"
            needs_reconnect = True
        elif ch.token_status == "expired":
            status = "expired"
            message = "Token expired, perlu reconnect"
            needs_reconnect = True
        elif ch.token_expires_at:
            exp = ch.token_expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            if exp < now:
                status = "expired"
                message = "Token expired sejak " + exp.isoformat()
                needs_reconnect = True
            elif (exp - now) < timedelta(hours=1):
                status = "expiring_soon"
                minutes_left = (exp - now).total_seconds() / 60
                message = "Token akan expired dalam " + str(int(minutes_left)) + " menit"
                needs_reconnect = True
            else:
                status = "valid"
                message = "Token valid sampai " + exp.isoformat()
        else:
            status = "unknown"
            message = "Status token tidak diketahui"

        health.append({
            "channel_id": ch.id,
            "channel_name": ch.name,
            "token_status": status,
            "message": message,
            "needs_reconnect": needs_reconnect,
            "expires_at": ch.token_expires_at.isoformat() if ch.token_expires_at else None,
            "last_checked": ch.token_checked_at.isoformat() if ch.token_checked_at else None,
        })

    all_valid = all(h["token_status"] == "valid" for h in health)
    any_error = any(h["needs_reconnect"] for h in health)

    return {
        "all_valid": all_valid,
        "any_error": any_error,
        "channels": health,
    }

@router.get("/{channel_id}", response_model=ChannelResponse)
async def get_channel(channel_id: int, db: AsyncSession = Depends(get_db)):
    """Get channel by ID."""
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # Auto-compute last activity
    last_upload, last_livestream = await _get_last_activity(db, channel_id)
    try:
        if last_upload and (not channel.last_upload or last_upload > channel.last_upload):
            channel.last_upload = last_upload
        if last_livestream and (not channel.last_livestream or last_livestream > channel.last_livestream):
            channel.last_livestream = last_livestream
        await db.commit()
    except Exception:
        pass

    return channel


@router.post("", response_model=ChannelResponse)
async def create_channel(data: ChannelCreate, db: AsyncSession = Depends(get_db)):
    """Create a new channel."""
    channel = Channel(**data.model_dump())
    db.add(channel)
    await db.flush()
    await db.refresh(channel)
    return channel


@router.put("/{channel_id}", response_model=ChannelResponse)
async def update_channel(channel_id: int, data: ChannelUpdate, db: AsyncSession = Depends(get_db)):
    """Update channel."""
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(channel, key, value)

    await db.flush()
    await db.refresh(channel)
    return channel


@router.delete("/{channel_id}")
async def delete_channel(channel_id: int, db: AsyncSession = Depends(get_db)):
    """Delete channel and ALL related data (media files, jobs, uploads, livestreams, pipelines)."""
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # 1. Delete physical media files
    media_items = (await db.execute(
        select(MediaItem).where(MediaItem.channel_id == channel_id)
    )).scalars().all()
    for item in media_items:
        storage.delete_file(item.file_path)

    # 2. Delete entire channel storage directory
    channel_storage = storage.base_path / "assets"
    for asset_dir in channel_storage.iterdir():
        if asset_dir.is_dir():
            ch_dir = asset_dir / str(channel_id)
            if ch_dir.exists():
                shutil.rmtree(ch_dir)

    # 3. Delete all DB records (order matters for foreign keys)
    await db.execute(delete(UploadBatchItem).where(UploadBatchItem.channel_id == channel_id))
    await db.execute(delete(UploadBatch).where(UploadBatch.channel_id == channel_id))
    await db.execute(delete(PipelineRun).where(PipelineRun.channel_id == channel_id))
    await db.execute(delete(Pipeline).where(Pipeline.channel_id == channel_id))
    await db.execute(delete(LiveJob).where(LiveJob.channel_id == channel_id))
    await db.execute(delete(ProductionJob).where(ProductionJob.channel_id == channel_id))
    await db.execute(delete(MediaItem).where(MediaItem.channel_id == channel_id))
    await db.execute(delete(AssetUsageLog).where(AssetUsageLog.channel_id == channel_id))

    # 4. Delete the channel itself
    await db.delete(channel)
    await db.flush()

    return {"success": True, "message": f"Channel '{channel.name}' and all related data deleted"}


@router.get("/{channel_id}/storage")
async def get_channel_storage(channel_id: int, db: AsyncSession = Depends(get_db)):
    """Get storage stats for a channel."""
    from app.services.storage import storage

    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    stats = storage.get_channel_stats(channel_id)
    return {"channel_id": channel_id, "stats": stats}
