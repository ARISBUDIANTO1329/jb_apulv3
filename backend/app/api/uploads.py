from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone

from app.db.session import get_db
from app.models.upload import UploadBatch, UploadBatchItem
from app.models.production import ProductionJob
from app.models.metadata import MetadataTitlePool, MetadataDescriptionPool, MetadataTagPool

def truncate_tags(tags_str: str, max_total: int = 500, max_per_tag: int = 30) -> str:
    """Truncate tags to fit YouTube limits: 500 chars total, 30 chars per tag."""
    if not tags_str:
        return ""
    # Split, clean, deduplicate
    tags = [t.strip()[:max_per_tag] for t in tags_str.split(",") if t.strip()]
    # Remove duplicates while preserving order
    seen = set()
    unique = []
    for t in tags:
        if t.lower() not in seen:
            seen.add(t.lower())
            unique.append(t)
    # Truncate to fit max_total
    result = []
    total = 0
    for t in unique:
        if total + len(t) + (2 if result else 0) > max_total:
            break
        result.append(t)
        total += len(t) + (2 if result else 0)
    return ", ".join(result)

from app.models.channel import Channel
from app.models.media import MediaItem
from app.services.storage import storage

router = APIRouter()


class UploadRequest(BaseModel):
    channel_id: int
    production_job_id: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[str] = None
    visibility: str = "scheduled"
    scheduled_at: Optional[str] = None  # ISO format
    thumbnail_path: Optional[str] = None


class ClipboardSave(BaseModel):
    channel_id: int
    content: str


@router.get("")
async def list_batches(
    channel_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List upload batches."""
    query = select(UploadBatch)
    if channel_id:
        query = query.where(UploadBatch.channel_id == channel_id)
    query = query.order_by(UploadBatch.created_at.desc())
    result = await db.execute(query)
    batches = result.scalars().all()

    return [{
        "id": b.id,
        "channel_id": b.channel_id,
        "name": b.name,
        "status": b.status,
        "total_items": b.total_items,
        "done_items": b.done_items,
        "created_at": b.created_at.isoformat() if b.created_at else None,
    } for b in batches]


@router.get("/items")
async def list_items(
    channel_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List upload items."""
    query = select(UploadBatchItem)
    if channel_id:
        query = query.where(UploadBatchItem.channel_id == channel_id)
    if status:
        query = query.where(UploadBatchItem.status == status)
    query = query.order_by(UploadBatchItem.created_at.desc())
    result = await db.execute(query)
    items = result.scalars().all()

    return [{
        "id": item.id,
        "upload_batch_id": item.upload_batch_id,
        "channel_id": item.channel_id,
        "title": item.title,
        "youtube_video_id": item.youtube_video_id,
        "scheduled_at": item.scheduled_at.isoformat() if item.scheduled_at else None,
        "visibility": item.visibility,
        "status": item.status,
        "progress": item.progress or 0,
        "last_error": item.last_error,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    } for item in items]


@router.get("/stats")
async def get_upload_stats(
    channel_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Get upload statistics for a channel."""
    result = await db.execute(
        select(UploadBatchItem).where(UploadBatchItem.channel_id == channel_id)
    )
    items = result.scalars().all()

    stats = {
        "total": len(items),
        "pending": sum(1 for i in items if i.status == "pending"),
        "processing": sum(1 for i in items if i.status == "processing"),
        "done": sum(1 for i in items if i.status == "done"),
        "failed": sum(1 for i in items if i.status == "failed"),
    }
    return stats


@router.post("")
async def create_upload(data: UploadRequest, db: AsyncSession = Depends(get_db)):
    """Create an upload batch from a production job or manual file."""
    # Verify channel
    result = await db.execute(select(Channel).where(Channel.id == data.channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # If production_job_id provided, get the final file
    source_path = None
    title = data.title
    if data.production_job_id:
        result = await db.execute(select(ProductionJob).where(ProductionJob.id == data.production_job_id))
        job = result.scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail="Production job not found")
        if job.final_status != "done" or not job.final_path:
            raise HTTPException(status_code=400, detail="Production job not finished")
        source_path = job.final_path
        if not title:
            title = job.output_filename

    # Get metadata from pools if not provided
    if not title:
        title = await _get_from_pool(db, MetadataTitlePool, data.channel_id)
    if not data.description:
        data.description = await _get_from_pool(db, MetadataDescriptionPool, data.channel_id)
    if not data.tags:
        data.tags = await _get_from_pool(db, MetadataTagPool, data.channel_id)
    # Always validate tags
    if data.tags:
        data.tags = truncate_tags(data.tags)

    # Create batch
    batch = UploadBatch(
        channel_id=data.channel_id,
        name=f"Upload {data.channel_id}",
        total_items=1,
    )
    db.add(batch)
    await db.flush()

    # Parse scheduled_at if provided
    scheduled_at_dt = None
    if data.scheduled_at:
        try:
            from dateutil import parser as date_parser
            scheduled_at_dt = date_parser.parse(data.scheduled_at)
        except Exception:
            # Try manual parsing
            try:
                scheduled_at_dt = datetime.fromisoformat(data.scheduled_at.replace('Z', '+00:00'))
            except Exception:
                pass

    # Create item
    item = UploadBatchItem(
        upload_batch_id=batch.id,
        channel_id=data.channel_id,
        title=title,
        description=data.description,
        tags=data.tags,
        visibility=data.visibility,
        scheduled_at=scheduled_at_dt,
        source_path=source_path,
        thumbnail_path=data.thumbnail_path,
        status="pending",
    )
    db.add(item)
    await db.flush()

    return {
        "success": True,
        "batch_id": batch.id,
        "item_id": item.id,
        "title": title,
        "source_path": source_path,
        "thumbnail_path": data.thumbnail_path,
        "status": "pending",
    }


# ── Bank Title ──────────────────────────────────────────────────


@router.get("/bank-title")
async def list_bank_titles(
    channel_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """List all titles in the bank for a channel."""
    result = await db.execute(
        select(MetadataTitlePool)
        .where(MetadataTitlePool.channel_id == channel_id)
        .order_by(MetadataTitlePool.created_at.desc())
    )
    items = result.scalars().all()
    return [{"id": t.id, "title": t.title, "used_at": t.used_at.isoformat() if t.used_at else None} for t in items]


@router.post("/bank-title")
async def upload_bank_title(
    channel_id: int = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a bank title file (one title per line)."""
    content = await file.read()
    text = content.decode("utf-8", errors="replace")
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    added = 0
    for line in lines:
        title = MetadataTitlePool(channel_id=channel_id, title=line)
        db.add(title)
        added += 1

    await db.flush()
    return {"success": True, "added": added}


@router.get("/bank-title/random")
async def get_random_title(
    channel_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Get a random unused title from the bank."""
    title = await _get_from_pool(db, MetadataTitlePool, channel_id)
    if not title:
        raise HTTPException(status_code=404, detail="No available title in bank")
    return {"title": title}


# ── Clipboard ───────────────────────────────────────────────────


@router.post("/clipboard-description")
async def save_description_clipboard(data: ClipboardSave, db: AsyncSession = Depends(get_db)):
    """Save description to metadata pool."""
    item = MetadataDescriptionPool(channel_id=data.channel_id, description=data.content)
    db.add(item)
    await db.flush()
    return {"success": True}


@router.get("/clipboard-description")
async def get_description_clipboard(
    channel_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Get description from metadata pool."""
    desc = await _get_from_pool(db, MetadataDescriptionPool, channel_id)
    return {"description": desc or ""}


@router.post("/clipboard-tags")
async def save_tags_clipboard(data: ClipboardSave, db: AsyncSession = Depends(get_db)):
    """Save tags to metadata pool with YouTube validation."""
    validated = truncate_tags(data.content)
    if not validated:
        raise HTTPException(status_code=400, detail="Tags kosong setelah validasi")
    item = MetadataTagPool(channel_id=data.channel_id, tags=validated)
    db.add(item)
    await db.flush()
    return {"success": True, "tags": validated}


@router.get("/clipboard-tags")
async def get_tags_clipboard(
    channel_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Get tags from metadata pool."""
    tags = await _get_from_pool(db, MetadataTagPool, channel_id)
    return {"tags": tags or ""}


# ── Upload Ready Files ──────────────────────────────────────────


@router.get("/upload-ready")
async def list_upload_ready(
    channel_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """List files in upload_ready folder for a channel."""
    files = storage.list_files(channel_id, "upload_ready")
    return {"channel_id": channel_id, "files": files}


# ── Schedule Preview ────────────────────────────────────────────


class SchedulePreviewRequest(BaseModel):
    channel_id: int
    mode: str  # single_schedule, double_schedule
    start_date: str  # YYYY-MM-DD
    start_time: str  # HH:MM
    interval: int = 1  # days between uploads


class BatchCreateRequest(BaseModel):
    channel_id: int
    mode: str
    rows: list  # preview rows from schedule


@router.post("/preview-schedule")
async def preview_schedule(data: SchedulePreviewRequest, db: AsyncSession = Depends(get_db)):
    """Preview scheduled upload with auto metadata from pools."""
    if data.mode not in ("single_schedule", "double_schedule"):
        raise HTTPException(status_code=400, detail="Mode must be single_schedule or double_schedule")

    # Get upload_ready media items
    result = await db.execute(
        select(MediaItem)
        .where(MediaItem.channel_id == data.channel_id)
        .where(MediaItem.asset_type == "upload_ready")
        .order_by(MediaItem.id.desc())
        .limit(50)
    )
    ready_items = result.scalars().all()

    if not ready_items:
        raise HTTPException(status_code=404, detail="Upload Ready kosong untuk channel ini")

    # Get title pool
    title_result = await db.execute(
        select(MetadataTitlePool)
        .where(MetadataTitlePool.channel_id == data.channel_id)
        .where(MetadataTitlePool.used_at.is_(None))
        .order_by(MetadataTitlePool.id.asc())
    )
    title_pools = title_result.scalars().all()

    if len(title_pools) < len(ready_items):
        raise HTTPException(
            status_code=422,
            detail=f"Title Pool tidak cukup. Butuh: {len(ready_items)}, Tersedia: {len(title_pools)}"
        )

    # Get description bank
    desc_result = await db.execute(
        select(MetadataDescriptionPool)
        .where(MetadataDescriptionPool.channel_id == data.channel_id)
        .where(MetadataDescriptionPool.used_at.is_(None))
        .order_by(MetadataDescriptionPool.id.asc())
    )
    desc_pools = desc_result.scalars().all()

    # Get tags bank
    tags_result = await db.execute(
        select(MetadataTagPool)
        .where(MetadataTagPool.channel_id == data.channel_id)
        .where(MetadataTagPool.used_at.is_(None))
        .order_by(MetadataTagPool.id.asc())
    )
    tags_pools = tags_result.scalars().all()

    # Build schedule rows
    from datetime import timedelta
    import random

    base_time = datetime.strptime(f"{data.start_date} {data.start_time}", "%Y-%m-%d %H:%M")
    interval = max(1, data.interval)

    rows = []
    for i, item in enumerate(ready_items):
        # Calculate scheduled time
        if data.mode == "double_schedule":
            day_index = i // 2
            slot_hour = 0 if i % 2 == 0 else 12
            slot_time = base_time + timedelta(days=day_index * interval, hours=slot_hour)
            slot_label = "Slot 1 (Pagi)" if i % 2 == 0 else "Slot 2 (Malam)"
        else:
            day_index = i
            slot_time = base_time + timedelta(days=i * interval)
            slot_label = "Single"

        # Pick title from pool
        title_pool = title_pools[i] if i < len(title_pools) else None
        title = title_pool.title if title_pool else ""

        # Pick description
        description = desc_pools[0].description if desc_pools else ""

        # Pick tags
        tags = tags_pools[0].tags if tags_pools else ""

        # Check file exists
        file_path = item.file_path or ""
        file_status = "ready" if file_path and storage.file_exists(file_path) else "missing"

        rows.append({
            "media_item_id": item.id,
            "slot_day": day_index + 1,
            "slot_label": slot_label,
            "scheduled_at": slot_time.strftime("%Y-%m-%dT%H:%M"),
            "scheduled_at_label": slot_time.strftime("%d %b %Y %H:%M"),
            "video_name": item.original_name or item.filename,
            "video_path": file_path,
            "file_status": file_status,
            "title": title,
            "title_pool_id": title_pool.id if title_pool else None,
            "description": description,
            "tags": tags,
            "is_ready": file_status == "ready" and bool(title),
        })

    return {
        "ok": True,
        "mode": data.mode,
        "total_rows": len(rows),
        "rows": rows,
    }


@router.post("/batch")
async def create_batch(data: BatchCreateRequest, db: AsyncSession = Depends(get_db)):
    """Create upload batch from schedule preview rows."""
    if not data.rows:
        raise HTTPException(status_code=400, detail="No rows provided")

    # Filter only ready rows
    ready_rows = [r for r in data.rows if r.get("is_ready", False)]
    if not ready_rows:
        raise HTTPException(status_code=400, detail="No ready rows to upload")

    # Create batch
    batch = UploadBatch(
        channel_id=data.channel_id,
        name=f"Schedule {data.mode} — {len(ready_rows)} videos",
        total_items=len(ready_rows),
        status="pending",
    )
    db.add(batch)
    await db.flush()
    await db.refresh(batch)

    # Create items
    for row in ready_rows:
        # Mark title as used
        title_pool_id = row.get("title_pool_id")
        if title_pool_id:
            title_item = await db.execute(
                select(MetadataTitlePool).where(MetadataTitlePool.id == title_pool_id)
            )
            title_obj = title_item.scalar_one_or_none()
            if title_obj:
                title_obj.used_at = datetime.now(timezone.utc)

        # Parse scheduled_at
        scheduled_at = None
        if row.get("scheduled_at"):
            try:
                scheduled_at = datetime.fromisoformat(row["scheduled_at"])
            except Exception:
                pass

        item = UploadBatchItem(
            upload_batch_id=batch.id,
            channel_id=data.channel_id,
            title=row.get("title", ""),
            description=row.get("description", ""),
            tags=row.get("tags", ""),
            visibility="scheduled",
            scheduled_at=scheduled_at,
            source_path=row.get("video_path", ""),
            status="pending",
        )
        db.add(item)

    await db.flush()

    return {
        "ok": True,
        "batch_id": batch.id,
        "total_items": len(ready_rows),
        "mode": data.mode,
        "message": f"Batch upload created: {len(ready_rows)} video dijadwalkan ({data.mode}).",
    }


# ── Retry / Delete ──────────────────────────────────────────────


@router.post("/{item_id}/retry")
async def retry_upload(item_id: int, db: AsyncSession = Depends(get_db)):
    """Retry a failed upload."""
    result = await db.execute(select(UploadBatchItem).where(UploadBatchItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if item.status != "failed":
        raise HTTPException(status_code=400, detail="Item is not in failed state")

    item.status = "pending"
    item.last_error = None
    item.progress = 0
    return {"success": True, "status": "pending"}


@router.delete("/{item_id}")
async def delete_item(item_id: int, db: AsyncSession = Depends(get_db)):
    """Delete an upload item."""
    result = await db.execute(select(UploadBatchItem).where(UploadBatchItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    await db.delete(item)
    return {"success": True}


# ── Helpers ──────────────────────────────────────────────────────


async def _get_from_pool(db: AsyncSession, model, channel_id: int) -> Optional[str]:
    """Get an unused item from a metadata pool."""
    cutoff = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    result = await db.execute(
        select(model)
        .where(model.channel_id == channel_id)
        .where((model.used_at.is_(None)) | (model.used_at < cutoff))
        .order_by(model.used_at.asc().nullsfirst())
        .limit(1)
    )
    item = result.scalar_one_or_none()
    if item:
        item.used_at = datetime.now(timezone.utc)
        return item.description if hasattr(item, 'description') else item.title if hasattr(item, 'title') else item.tags
    return None
