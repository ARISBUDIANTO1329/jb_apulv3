"""
Metadata Pool CRUD API - JB APUL v3
Per-pool CRUD for title, description, tag, playlist.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone

from app.db.session import get_db
from app.models.metadata import MetadataTitlePool, MetadataDescriptionPool, MetadataTagPool, MetadataPlaylistPool

router = APIRouter()

# ── Pool registry ──────────────────────────────────────────────

POOLS = {
    "title": {
        "model": MetadataTitlePool,
        "field": "title",
        "label": "Judul",
    },
    "description": {
        "model": MetadataDescriptionPool,
        "field": "description",
        "label": "Deskripsi",
    },
    "tag": {
        "model": MetadataTagPool,
        "field": "tags",
        "label": "Tag",
    },
    "playlist": {
        "model": MetadataPlaylistPool,
        "field": "playlist_name",
        "label": "Playlist",
    },
}

def _get_pool(pool_type: str):
    if pool_type not in POOLS:
        raise HTTPException(400, f"Tipe pool tidak valid: {pool_type}")
    return POOLS[pool_type]


# ── Request models ─────────────────────────────────────────────

class ItemCreate(BaseModel):
    channel_id: int
    content: str

class ItemUpdate(BaseModel):
    content: str

class ClipboardSave(BaseModel):
    channel_id: int
    content: str


# ── List (paginated) ──────────────────────────────────────────

@router.get("/{pool_type}")
async def list_items(
    pool_type: str,
    channel_id: int = Query(...),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    q: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List items in a metadata pool."""
    pool = _get_pool(pool_type)
    model = pool["model"]
    field_name = pool["field"]
    field_col = getattr(model, field_name)

    query = select(model).where(model.channel_id == channel_id)
    if q:
        query = query.where(field_col.ilike(f"%{q}%"))

    # Count
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Paginate
    query = query.order_by(model.id.asc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    items = result.scalars().all()

    return {
        "items": [
            {
                "id": item.id,
                "content": getattr(item, field_name),
                "used_at": item.used_at.isoformat() if item.used_at else None,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in items
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


# ── Stats ──────────────────────────────────────────────────────

@router.get("/{pool_type}/stats")
async def pool_stats(
    pool_type: str,
    channel_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Get count and used count for a pool."""
    pool = _get_pool(pool_type)
    model = pool["model"]

    total_q = select(func.count()).where(model.channel_id == channel_id)
    total = (await db.execute(total_q)).scalar() or 0

    used_q = select(func.count()).where(model.channel_id == channel_id, model.used_at.isnot(None))
    used = (await db.execute(used_q)).scalar() or 0

    return {"total": total, "used": used, "remaining": total - used}


# ── Create single ─────────────────────────────────────────────

@router.post("/{pool_type}")
async def create_item(
    pool_type: str,
    data: ItemCreate,
    db: AsyncSession = Depends(get_db),
):
    """Add a single item to a pool."""
    pool = _get_pool(pool_type)
    model = pool["model"]
    field_name = pool["field"]

    if not data.content.strip():
        raise HTTPException(400, "Content tidak boleh kosong")

    item = model(channel_id=data.channel_id, **{field_name: data.content.strip()})
    db.add(item)
    await db.flush()

    return {"success": True, "id": item.id, "content": data.content.strip()}


# ── Update single ─────────────────────────────────────────────

@router.put("/{pool_type}/{item_id}")
async def update_item(
    pool_type: str,
    item_id: int,
    data: ItemUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a single item."""
    pool = _get_pool(pool_type)
    model = pool["model"]
    field_name = pool["field"]

    result = await db.execute(select(model).where(model.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Item tidak ditemukan")

    if not data.content.strip():
        raise HTTPException(400, "Content tidak boleh kosong")

    setattr(item, field_name, data.content.strip())
    await db.flush()

    return {"success": True, "id": item.id, "content": data.content.strip()}


# ── Delete single ─────────────────────────────────────────────

@router.delete("/{pool_type}/{item_id}")
async def delete_item(
    pool_type: str,
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a single item."""
    pool = _get_pool(pool_type)
    model = pool["model"]

    result = await db.execute(select(model).where(model.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Item tidak ditemukan")

    await db.delete(item)
    await db.flush()

    return {"success": True, "deleted_id": item_id}


# ── Bulk upload (APPEND) ──────────────────────────────────────

@router.post("/{pool_type}/upload")
async def upload_items(
    pool_type: str,
    channel_id: int = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a .txt file. One item per line. APPENDS to existing pool."""
    pool = _get_pool(pool_type)
    model = pool["model"]
    field_name = pool["field"]

    content = await file.read()
    text = content.decode("utf-8", errors="replace")
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    if not lines:
        raise HTTPException(400, "File kosong")

    added = 0
    for line in lines:
        item = model(channel_id=channel_id, **{field_name: line})
        db.add(item)
        added += 1

    await db.flush()

    return {"success": True, "added": added, "filename": file.filename}


# ── Delete all for channel ────────────────────────────────────

@router.delete("/{pool_type}/all")
async def delete_all_items(
    pool_type: str,
    channel_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Delete all items in a pool for a channel."""
    pool = _get_pool(pool_type)
    model = pool["model"]

    result = await db.execute(select(model).where(model.channel_id == channel_id))
    items = result.scalars().all()
    count = len(items)
    for item in items:
        await db.delete(item)

    await db.flush()

    return {"success": True, "deleted": count}


# ── Reset used_at for all ─────────────────────────────────────

@router.post("/{pool_type}/reset-usage")
async def reset_usage(
    pool_type: str,
    channel_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Reset used_at for all items in pool (start rotation over)."""
    pool = _get_pool(pool_type)
    model = pool["model"]

    result = await db.execute(select(model).where(model.channel_id == channel_id))
    items = result.scalars().all()
    for item in items:
        item.used_at = None

    await db.flush()

    return {"success": True, "reset": len(items)}


# ── Clipboard endpoints (for backwards compat) ───────────────

@router.post("/clipboard/{pool_type}")
async def save_clipboard(
    pool_type: str,
    data: ClipboardSave,
    db: AsyncSession = Depends(get_db),
):
    """Save clipboard content to pool (single item)."""
    pool = _get_pool(pool_type)
    model = pool["model"]
    field_name = pool["field"]

    item = model(channel_id=data.channel_id, **{field_name: data.content.strip()})
    db.add(item)
    await db.flush()

    return {"success": True, "id": item.id}
