"""
Estafet API - JB APUL v3
Multi-video livestream with automatic sequencing and breaks
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone

from app.db.session import get_db
from app.models.estafet import EstafetJob, EstafetItem
from app.models.media import MediaItem
from app.models.channel import Channel

router = APIRouter()


class EstafetRequest(BaseModel):
    channel_id: int
    title: str
    video_ids: List[int]
    duration_hours: int = 12
    break_minutes: int = 60
    quality: str = "low"
    use_mp3: bool = True
    use_sfx: bool = True


@router.post("")
async def create_estafet(req: EstafetRequest, db: AsyncSession = Depends(get_db)):
    """Create estafet job with multiple videos"""

    # Validate channel
    channel = await db.get(Channel, req.channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")

    # Get media items
    media_items = []
    for vid_id in req.video_ids:
        media = await db.get(MediaItem, vid_id)
        if not media:
            raise HTTPException(404, f"Media item {vid_id} not found")
        if media.asset_type != "livestream-ready":
            raise HTTPException(400, f"Media {vid_id} is not livestream-ready")
        media_items.append(media)

    # Create estafet job
    job = EstafetJob(
        channel_id=req.channel_id,
        title=req.title,
        duration_hours=req.duration_hours,
        break_minutes=req.break_minutes,
        quality=req.quality,
        use_mp3=req.use_mp3,
        use_sfx=req.use_sfx,
        status="pending",
    )
    db.add(job)
    await db.flush()

    # Create estafet items
    for idx, media in enumerate(media_items):
        item = EstafetItem(
            estafet_job_id=job.id,
            media_item_id=media.id,
            video_order=idx + 1,
            title=f"{req.title}: {media.title or media.filename}",
            description=media.note or "",
            tags=media.tags or "",
            status="pending",
        )
        db.add(item)

    await db.commit()

    return {"success": True, "job_id": job.id, "message": f"Estafet created with {len(media_items)} videos"}


@router.get("")
async def list_estafet_jobs(
    channel_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    """List estafet jobs"""
    query = select(EstafetJob)
    if channel_id:
        query = query.where(EstafetJob.channel_id == channel_id)
    query = query.order_by(EstafetJob.created_at.desc())

    result = await db.execute(query)
    jobs = result.scalars().all()

    return [
        {
            "id": job.id,
            "channel_id": job.channel_id,
            "title": job.title,
            "duration_hours": job.duration_hours,
            "break_minutes": job.break_minutes,
            "quality": job.quality,
            "use_mp3": job.use_mp3,
            "use_sfx": job.use_sfx,
            "status": job.status,
            "current_video_index": job.current_video_index,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
        }
        for job in jobs
    ]


@router.get("/{job_id}")
async def get_estafet_job(job_id: int, db: AsyncSession = Depends(get_db)):
    """Get estafet job details with items"""
    job = await db.get(EstafetJob, job_id)
    if not job:
        raise HTTPException(404, "Estafet job not found")

    # Get items
    query = (
        select(EstafetItem)
        .where(EstafetItem.estafet_job_id == job_id)
        .order_by(EstafetItem.video_order)
    )
    result = await db.execute(query)
    items = result.scalars().all()

    return {
        "id": job.id,
        "channel_id": job.channel_id,
        "title": job.title,
        "duration_hours": job.duration_hours,
        "break_minutes": job.break_minutes,
        "quality": job.quality,
        "use_mp3": job.use_mp3,
        "use_sfx": job.use_sfx,
        "status": job.status,
        "current_video_index": job.current_video_index,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "items": [
            {
                "id": item.id,
                "media_item_id": item.media_item_id,
                "video_order": item.video_order,
                "title": item.title,
                "description": item.description,
                "tags": item.tags,
                "thumbnail_path": item.thumbnail_path,
                "status": item.status,
                "youtube_broadcast_id": item.youtube_broadcast_id,
                "started_at": item.started_at.isoformat() if item.started_at else None,
                "finished_at": item.finished_at.isoformat() if item.finished_at else None,
            }
            for item in items
        ],
    }


@router.post("/{job_id}/stop")
async def stop_estafet(job_id: int, db: AsyncSession = Depends(get_db)):
    """Stop estafet job"""
    job = await db.get(EstafetJob, job_id)
    if not job:
        raise HTTPException(404, "Estafet job not found")

    job.status = "stopped"
    await db.commit()

    return {"success": True, "message": "Estafet stopped"}


@router.delete("/{job_id}")
async def delete_estafet(job_id: int, db: AsyncSession = Depends(get_db)):
    """Delete estafet job and items"""
    job = await db.get(EstafetJob, job_id)
    if not job:
        raise HTTPException(404, "Estafet job not found")

    if job.status == "running":
        raise HTTPException(400, "Cannot delete running estafet. Stop it first.")

    # Delete items
    query = select(EstafetItem).where(EstafetItem.estafet_job_id == job_id)
    result = await db.execute(query)
    items = result.scalars().all()
    for item in items:
        await db.delete(item)

    await db.delete(job)
    await db.commit()

    return {"success": True, "message": "Estafet deleted"}
