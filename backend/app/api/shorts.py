"""
Shorts API - Generate and schedule shorts from completed uploads.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone

from app.db.session import get_db
from app.models.shorts import ShortsJob, ShortsItem
from app.models.upload import UploadBatchItem
from app.models.channel import Channel
from app.models.media import MediaItem
from app.models.production import ProductionJob

router = APIRouter()


# ── Request Models ──────────────────────────────────────────────

class ShortsCreateRequest(BaseModel):
    channel_id: int
    long_upload_id: int  # upload_batch_items.id
    short_count: int = 3
    short_duration: int = 60
    segment_mode: str = "auto"  # auto / manual
    description_template: Optional[str] = None
    upload_time_1: str = "12:00"
    upload_time_2: str = "16:00"
    upload_time_3: str = "20:00"


# ── Endpoints ──────────────────────────────────────────────────

@router.get("")
async def list_jobs(
    channel_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List all shorts jobs."""
    query = select(ShortsJob)
    if channel_id:
        query = query.where(ShortsJob.channel_id == channel_id)
    if status:
        query = query.where(ShortsJob.status == status)
    query = query.order_by(ShortsJob.created_at.desc())
    result = await db.execute(query)
    jobs = result.scalars().all()

    jobs_data = []
    for job in jobs:
        # Get channel name
        ch_result = await db.execute(select(Channel).where(Channel.id == job.channel_id))
        channel = ch_result.scalar_one_or_none()

        # Get shorts items
        items_result = await db.execute(
            select(ShortsItem).where(ShortsItem.job_id == job.id).order_by(ShortsItem.short_number)
        )
        items = items_result.scalars().all()

        jobs_data.append({
            "id": job.id,
            "channel_id": job.channel_id,
            "channel_name": channel.name if channel else f"Channel {job.channel_id}",
            "long_upload_id": job.long_upload_id,
            "long_youtube_url": job.long_youtube_url,
            "long_title": job.long_title,
            "short_count": job.short_count,
            "short_duration": job.short_duration,
            "segment_mode": job.segment_mode,
            "description_template": job.description_template,
            "upload_time_1": job.upload_time_1,
            "upload_time_2": job.upload_time_2,
            "upload_time_3": job.upload_time_3,
            "status": job.status,
            "error_message": job.error_message,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "items": [{
                "id": item.id,
                "short_number": item.short_number,
                "video_path": item.video_path,
                "start_second": item.start_second,
                "end_second": item.end_second,
                "title": item.title,
                "description": item.description,
                "youtube_id": item.youtube_id,
                "upload_time": item.upload_time,
                "status": item.status,
                "error_message": item.error_message,
                "uploaded_at": item.uploaded_at.isoformat() if item.uploaded_at else None,
            } for item in items],
        })

    return jobs_data


@router.get("/completed-uploads")
async def list_completed_uploads(
    channel_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List completed uploads that can be used for shorts generation."""
    # Get upload IDs that already have shorts jobs
    existing_shorts = await db.execute(
        select(ShortsJob.long_upload_id).where(ShortsJob.long_upload_id.isnot(None))
    )
    used_upload_ids = [row[0] for row in existing_shorts.fetchall()]

    query = select(UploadBatchItem).where(UploadBatchItem.status == "done")
    if channel_id:
        query = query.where(UploadBatchItem.channel_id == channel_id)
    # Exclude uploads that already have shorts
    if used_upload_ids:
        query = query.where(UploadBatchItem.id.notin_(used_upload_ids))
    query = query.order_by(UploadBatchItem.created_at.desc()).limit(50)
    result = await db.execute(query)
    items = result.scalars().all()

    uploads = []
    for item in items:
        # Get file size from production_jobs if available
        file_size = None
        file_size_mb = None
        video_path = item.source_path

        # Try to find the production job that created this upload
        if not video_path:
            prod_result = await db.execute(
                select(ProductionJob).where(
                    ProductionJob.channel_id == item.channel_id,
                    ProductionJob.status == "done",
                    ProductionJob.output_filename.isnot(None),
                ).order_by(ProductionJob.created_at.desc()).limit(1)
            )
            prod = prod_result.scalar_one_or_none()
            if prod and prod.final_path:
                video_path = prod.final_path

        # Get file size from filesystem
        if video_path:
            import os
            try:
                if os.path.exists(video_path):
                    file_size = os.path.getsize(video_path)
                    file_size_mb = round(file_size / (1024 * 1024), 1)
            except Exception:
                pass

        uploads.append({
            "id": item.id,
            "channel_id": item.channel_id,
            "title": item.title,
            "youtube_id": item.youtube_video_id,
            "youtube_url": f"https://youtube.com/watch?v={item.youtube_video_id}" if item.youtube_video_id else None,
            "video_path": video_path,
            "file_size": file_size,
            "file_size_mb": file_size_mb,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        })

    return uploads


@router.post("")
async def create_job(data: ShortsCreateRequest, db: AsyncSession = Depends(get_db)):
    """Create a shorts job from a completed upload."""
    # Validate channel
    ch_result = await db.execute(select(Channel).where(Channel.id == data.channel_id))
    channel = ch_result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # Validate upload
    upload_result = await db.execute(
        select(UploadBatchItem).where(UploadBatchItem.id == data.long_upload_id)
    )
    upload = upload_result.scalar_one_or_none()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    if upload.status != "done":
        raise HTTPException(status_code=400, detail="Upload belum selesai")
    if not upload.youtube_video_id:
        raise HTTPException(status_code=400, detail="Upload tidak memiliki YouTube ID")

    # Build description template if not provided
    long_url = f"https://youtube.com/watch?v={upload.youtube_video_id}"
    if not data.description_template:
        description_template = (
            f"Watch the full version here:\n{long_url}\n\n"
            f"#relaxation #music #sleep #meditation #ambient"
        )
    else:
        description_template = data.description_template.replace("{LONG_URL}", long_url)

    # Create job
    job = ShortsJob(
        channel_id=data.channel_id,
        long_upload_id=data.long_upload_id,
        long_youtube_url=long_url,
        long_title=upload.title,
        short_count=data.short_count,
        short_duration=data.short_duration,
        segment_mode=data.segment_mode,
        description_template=description_template,
        upload_time_1=data.upload_time_1,
        upload_time_2=data.upload_time_2,
        upload_time_3=data.upload_time_3,
        status="created",
    )
    db.add(job)
    await db.flush()

    # Create shorts items
    upload_times = [data.upload_time_1, data.upload_time_2, data.upload_time_3]
    for i in range(data.short_count):
        item = ShortsItem(
            job_id=job.id,
            short_number=i + 1,
            title=f"{upload.title} - Part {i + 1}" if upload.title else f"Short {i + 1}",
            description=description_template,
            upload_time=upload_times[i] if i < len(upload_times) else None,
            status="pending",
        )
        db.add(item)

    # Update job status
    job.status = "pending"
    await db.flush()

    return {
        "success": True,
        "job_id": job.id,
        "message": f"Shorts job created. {data.short_count} shorts will be generated and scheduled.",
    }


@router.get("/{job_id}")
async def get_job(job_id: int, db: AsyncSession = Depends(get_db)):
    """Get shorts job detail."""
    result = await db.execute(select(ShortsJob).where(ShortsJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Get channel
    ch_result = await db.execute(select(Channel).where(Channel.id == job.channel_id))
    channel = ch_result.scalar_one_or_none()

    # Get items
    items_result = await db.execute(
        select(ShortsItem).where(ShortsItem.job_id == job.id).order_by(ShortsItem.short_number)
    )
    items = items_result.scalars().all()

    return {
        "id": job.id,
        "channel_id": job.channel_id,
        "channel_name": channel.name if channel else f"Channel {job.channel_id}",
        "long_upload_id": job.long_upload_id,
        "long_youtube_url": job.long_youtube_url,
        "long_title": job.long_title,
        "short_count": job.short_count,
        "short_duration": job.short_duration,
        "segment_mode": job.segment_mode,
        "description_template": job.description_template,
        "upload_time_1": job.upload_time_1,
        "upload_time_2": job.upload_time_2,
        "upload_time_3": job.upload_time_3,
        "status": job.status,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "items": [{
            "id": item.id,
            "short_number": item.short_number,
            "video_path": item.video_path,
            "start_second": item.start_second,
            "end_second": item.end_second,
            "title": item.title,
            "description": item.description,
            "youtube_id": item.youtube_id,
            "upload_time": item.upload_time,
            "status": item.status,
            "error_message": item.error_message,
            "uploaded_at": item.uploaded_at.isoformat() if item.uploaded_at else None,
        } for item in items],
    }


@router.delete("/all")
async def delete_all_jobs(db: AsyncSession = Depends(get_db)):
    """Delete all shorts jobs and items."""
    # Delete all items first
    items_result = await db.execute(select(ShortsItem))
    items = items_result.scalars().all()
    for item in items:
        await db.delete(item)

    # Delete all jobs
    jobs_result = await db.execute(select(ShortsJob))
    jobs = jobs_result.scalars().all()
    count = len(jobs)
    for job in jobs:
        await db.delete(job)

    await db.commit()
    return {"success": True, "deleted": count}

@router.delete("/{job_id}")
async def delete_job(job_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a shorts job."""
    result = await db.execute(select(ShortsJob).where(ShortsJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Delete items first
    items_result = await db.execute(select(ShortsItem).where(ShortsItem.job_id == job.id))
    for item in items_result.scalars().all():
        await db.delete(item)

    await db.delete(job)
    await db.commit()
    return {"success": True}


@router.post("/{job_id}/retry")
async def retry_job(job_id: int, db: AsyncSession = Depends(get_db)):
    """Retry failed shorts items."""
    result = await db.execute(select(ShortsJob).where(ShortsJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Reset failed items to pending
    items_result = await db.execute(
        select(ShortsItem).where(ShortsItem.job_id == job.id, ShortsItem.status == "failed")
    )
    retry_count = 0
    for item in items_result.scalars().all():
        item.status = "pending"
        item.error_message = None
        retry_count += 1

    if retry_count > 0:
        job.status = "pending"
        job.error_message = None

    return {"success": True, "retry_count": retry_count}
