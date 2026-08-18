from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional, List
from pathlib import Path
import shutil
import os
import logging

log = logging.getLogger(__name__)

from app.db.session import get_db
from app.models.media import MediaItem
from app.models.channel import Channel
from app.services.storage import storage

router = APIRouter()

# ── Konstanta ──────────────────────────────────────────────────

ALLOWED_GROUPS = [
    "video", "video-raw", "video-live", "livestream-ready",
    "mp3", "sfx", "intro", "thumbnail", "metadata", "upload_ready",
]

GROUP_META = {
    "video": {"label": "Video", "desc": "Footage video utama"},
    "video-raw": {"label": "Video Raw", "desc": "Video mentah sebelum proses seamless"},
    "video-live": {"label": "Video Live", "desc": "Footage hasil live"},
    "livestream-ready": {"label": "Livestream Ready", "desc": "Video siap untuk livestream"},
    "mp3": {"label": "MP3", "desc": "Audio / musik / voice"},
    "sfx": {"label": "SFX", "desc": "Efek suara pendek"},
    "intro": {"label": "Intro", "desc": "Video pembuka"},
    "thumbnail": {"label": "Thumbnail", "desc": "Gambar thumbnail"},
    "metadata": {"label": "Metadata", "desc": "File metadata pendukung"},
    "upload_ready": {"label": "Upload Ready", "desc": "Video final siap upload YouTube"},
}

# Validasi tipe file per group
TYPE_VALIDATION = {
    "video": {"accept": "video/*", "ext": [".mp4", ".mkv", ".webm", ".mov", ".avi"], "msg": "Folder Video hanya menerima file video."},
    "video-raw": {"accept": "video/*", "ext": [".mp4", ".mkv", ".webm", ".mov", ".avi"], "msg": "Folder Video Raw hanya menerima file video."},
    "video-live": {"accept": "video/*", "ext": [".mp4", ".mkv", ".webm", ".mov", ".avi"], "msg": "Folder Video Live hanya menerima file video."},
    "livestream-ready": {"accept": "video/*", "ext": [".mp4", ".mkv", ".webm", ".mov", ".avi"], "msg": "Livestream Ready hanya menerima file video."},
    "upload_ready": {"accept": "video/*", "ext": [".mp4", ".mkv", ".webm", ".mov", ".avi"], "msg": "Upload Ready hanya menerima file video final."},
    "mp3": {"accept": ".mp3", "ext": [".mp3"], "msg": "Folder MP3 hanya menerima file .mp3."},
    "sfx": {"accept": "audio/*", "ext": [".mp3", ".wav", ".ogg", ".flac"], "msg": "Folder SFX hanya menerima file audio."},
    "intro": {"accept": "video/*", "ext": [".mp4", ".mkv", ".webm", ".mov", ".avi"], "msg": "Folder Intro hanya menerima file video."},
    "thumbnail": {"accept": "image/*", "ext": [".jpg", ".jpeg", ".png", ".gif", ".webp"], "msg": "Folder Thumbnail hanya menerima file image."},
    "metadata": {"accept": ".txt,.json,.csv,.md", "ext": [".txt", ".json", ".csv", ".md"], "msg": "Folder Metadata hanya menerima file txt, json, csv, atau md."},
}

TYPE_MAP = {
    "video": "video", "video-raw": "video", "video-live": "video",
    "livestream-ready": "video", "upload_ready": "video",
    "mp3": "audio", "sfx": "audio", "intro": "video",
    "thumbnail": "image", "metadata": "metadata",
}


# ── Helper ──────────────────────────────────────────────────────

def _format_bytes(b: int) -> str:
    if b <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    import math
    p = min(int(math.log(b, 1024)), len(units) - 1)
    return f"{b / (1024 ** p):,.{0 if p == 0 else 1}f} {units[p]}".replace(",", ".")


def _validate_file_type(group: str, filename: str, mime: str) -> bool:
    """Validasi tipe file berdasarkan group."""
    if group not in TYPE_VALIDATION:
        return False
    ext = Path(filename).suffix.lower()
    return ext in TYPE_VALIDATION[group]["ext"]


# ── Endpoints ──────────────────────────────────────────────────

@router.get("/groups")
async def list_groups():
    """Return available asset groups with metadata."""
    return GROUP_META


@router.get("/stats")
async def get_stats(
    channel_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Get count per asset group for a channel."""
    from app.models.metadata import MetadataTitlePool, MetadataDescriptionPool, MetadataTagPool, MetadataPlaylistPool, MetadataPlaylistPool
    
    result = await db.execute(
        select(
            MediaItem.asset_type,
            func.count(MediaItem.id),
            func.coalesce(func.sum(MediaItem.file_size), 0),
        )
        .where(MediaItem.channel_id == channel_id)
        .group_by(MediaItem.asset_type)
    )
    rows = result.all()
    stats = {}
    total_bytes = 0
    for asset_type, cnt, total in rows:
        stats[asset_type] = {"count": cnt, "total_bytes": total}
        total_bytes += total
    
    # Add metadata pool counts (per sub-type)
    title_count_result = await db.execute(
        select(func.count()).where(MetadataTitlePool.channel_id == channel_id)
    )
    title_count = title_count_result.scalar() or 0
    
    desc_count_result = await db.execute(
        select(func.count()).where(MetadataDescriptionPool.channel_id == channel_id)
    )
    desc_count = desc_count_result.scalar() or 0
    
    tag_count_result = await db.execute(
        select(func.count()).where(MetadataTagPool.channel_id == channel_id)
    )
    tag_count = tag_count_result.scalar() or 0

    playlist_count_result = await db.execute(
        select(func.count()).where(MetadataPlaylistPool.channel_id == channel_id)
    )
    playlist_count = playlist_count_result.scalar() or 0
    
    metadata_count = title_count + desc_count + tag_count + playlist_count
    
    # Fill missing groups
    for g in ALLOWED_GROUPS:
        if g not in stats:
            stats[g] = {"count": 0, "total_bytes": 0}
    
    # Override metadata count with pool data (show total)
    stats["metadata"] = {"count": metadata_count, "total_bytes": 0}
    
    # Add sub-type breakdown
    stats["metadata_title"] = {"count": title_count, "total_bytes": 0}
    stats["metadata_description"] = {"count": desc_count, "total_bytes": 0}
    stats["metadata_tag"] = {"count": tag_count, "total_bytes": 0}
    stats["metadata_playlist"] = {"count": playlist_count, "total_bytes": 0}
    
    return {"channel_id": channel_id, "stats": stats, "total_bytes": total_bytes}


@router.get("/disk")
async def get_disk_space():
    """Get server disk space info."""
    try:
        usage = shutil.disk_usage("/")
        total, used, free = usage.total, usage.used, usage.free
        percent = round((used / total) * 100, 1) if total > 0 else 0
    except Exception:
        total = used = free = 0
        percent = 0
    return {
        "total": total,
        "used": used,
        "free": free,
        "percent": percent,
        "total_fmt": _format_bytes(total),
        "used_fmt": _format_bytes(used),
        "free_fmt": _format_bytes(free),
    }


@router.get("")
async def list_media(
    channel_id: int = Query(..., description="Channel ID"),
    group: Optional[str] = Query(None, description="Filter by asset group"),
    category: Optional[str] = Query(None, description="Filter metadata by category"),
    q: Optional[str] = Query(None, description="Search query"),
    page: int = Query(1, ge=1),
    per_page: int = Query(12, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List media items for a channel with group filtering, search, and pagination."""
    
    # Special handling for metadata group - show uploaded files from MediaItem table
    if group == "metadata":
        # Query MediaItems with asset_type=metadata
        meta_query = select(MediaItem).where(
            MediaItem.channel_id == channel_id,
            MediaItem.asset_type == "metadata",
        )
        # Filter by category if specified
        if category:
            meta_query = meta_query.where(MediaItem.category == category)
        if q:
            search = f"%{q}%"
            meta_query = meta_query.where(
                MediaItem.original_name.ilike(search) | MediaItem.filename.ilike(search)
            )

        # Count total
        count_q = select(func.count()).select_from(meta_query.subquery())
        total_result = await db.execute(count_q)
        total = total_result.scalar() or 0

        # Paginate
        meta_query = meta_query.order_by(MediaItem.created_at.desc())
        meta_query = meta_query.offset((page - 1) * per_page).limit(per_page)
        result = await db.execute(meta_query)
        items = result.scalars().all()

        return {
            "items": [
                {
                    "id": item.id,
                    "filename": item.filename,
                    "original_name": item.original_name or item.filename,
                    "file_path": item.file_path,
                    "asset_type": item.asset_type,
                    "mime": item.mime,
                    "file_size": item.file_size or 0,
                    "duration": item.duration,
                    "title": item.title,
                    "status": item.status,
                    "category": item.category,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                    "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                }
                for item in items
            ],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
        }

    # Normal media items
    query = select(MediaItem).where(MediaItem.channel_id == channel_id)
    if group and group in ALLOWED_GROUPS:
        query = query.where(MediaItem.asset_type == group)
    if q:
        search = f"%{q}%"
        query = query.where(
            MediaItem.filename.ilike(search)
            | MediaItem.original_name.ilike(search)
            | MediaItem.title.ilike(search)
            | MediaItem.tags.ilike(search)
            | MediaItem.file_path.ilike(search)
        )
    # Count total
    count_q = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    # Paginate
    query = query.order_by(MediaItem.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    items = result.scalars().all()

    return {
        "items": [
            {
                "id": item.id,
                "filename": item.filename,
                "original_name": item.original_name or item.filename,
                "file_path": item.file_path,
                "asset_type": item.asset_type,
                "mime": item.mime,
                "file_size": item.file_size or 0,
                "duration": item.duration,
                "title": item.title,
                "status": item.status,
                "category": item.category,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            }
            for item in items
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


@router.post("/upload")
async def upload_media(
    channel_id: int = Form(...),
    asset_type: str = Form(...),
    metadata_category: Optional[str] = Form(None),
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload multiple media files for a channel."""
    if asset_type not in ALLOWED_GROUPS:
        raise HTTPException(status_code=400, detail=f"Asset type tidak valid: {asset_type}")

    # Verify channel
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel tidak ditemukan")

    import re
    import secrets

    uploaded = []
    errors = []

    for file in files:
        # Validate file type
        if not _validate_file_type(asset_type, file.filename, file.content_type or ""):
            msg = TYPE_VALIDATION.get(asset_type, {}).get("msg", "Tipe file tidak cocok.")
            errors.append({"filename": file.filename, "error": msg})
            continue

        # Generate safe filename
        orig = file.filename or "upload"
        ext = Path(orig).suffix.lower()
        base = re.sub(r"[^\w.\-]", "_", Path(orig).stem)
        if not base:
            base = "file"
        safe_name = f"{base}-{secrets.token_hex(4)}{ext}"

        # Stream file to disk directly (no full memory load)
        file.file.seek(0)
        file_path = storage.save_file_stream(channel_id, asset_type, safe_name, file.file)
        file_size = file.size or 0
        if not file_size:
            import os
            file_size = os.path.getsize(file_path)

        # For metadata parsing (small text files) read into memory
        content = None
        if asset_type == "metadata":
            file.file.seek(0)
            content = file.file.read()

        # Create DB record
        media_item = MediaItem(
            channel_id=channel_id,
            filename=safe_name,
            original_name=orig,
            file_path=file_path,
            asset_type=asset_type,
            mime=file.content_type,
            file_size=file_size,
        )
        db.add(media_item)
        await db.flush()

        # Parse metadata files and insert into pool tables
        if asset_type == "metadata" and metadata_category:
            from app.models.metadata import MetadataTitlePool, MetadataDescriptionPool, MetadataTagPool, MetadataPlaylistPool
            text = (content or b"").decode("utf-8", errors="replace")
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            
            if metadata_category == "title_bank":
                # Delete existing titles for this channel
                existing = await db.execute(
                    select(MetadataTitlePool).where(MetadataTitlePool.channel_id == channel_id)
                )
                for item in existing.scalars().all():
                    await db.delete(item)
                
                # Insert new titles
                for line in lines:
                    title = MetadataTitlePool(channel_id=channel_id, title=line)
                    db.add(title)
                log.info(f"Inserted {len(lines)} titles for channel {channel_id}")
            
            elif metadata_category == "description_bank":
                # Delete existing descriptions
                existing = await db.execute(
                    select(MetadataDescriptionPool).where(MetadataDescriptionPool.channel_id == channel_id)
                )
                for item in existing.scalars().all():
                    await db.delete(item)
                
                # Insert new descriptions
                for line in lines:
                    desc = MetadataDescriptionPool(channel_id=channel_id, description=line)
                    db.add(desc)
                log.info(f"Inserted {len(lines)} descriptions for channel {channel_id}")
            
            elif metadata_category == "tag_bank":
                # Delete existing tags
                existing = await db.execute(
                    select(MetadataTagPool).where(MetadataTagPool.channel_id == channel_id)
                )
                for item in existing.scalars().all():
                    await db.delete(item)
                
                # Insert new tags
                for line in lines:
                    tag = MetadataTagPool(channel_id=channel_id, tags=line)
                    db.add(tag)
                log.info(f"Inserted {len(lines)} tags for channel {channel_id}")
            
            elif metadata_category == "playlist_bank":
                # Delete existing playlists
                existing = await db.execute(
                    select(MetadataPlaylistPool).where(MetadataPlaylistPool.channel_id == channel_id)
                )
                for item in existing.scalars().all():
                    await db.delete(item)

                # Insert new playlists
                for line in lines:
                    playlist = MetadataPlaylistPool(channel_id=channel_id, playlist_name=line)
                    db.add(playlist)
                log.info(f"Inserted {len(lines)} playlists for channel {channel_id}")

            # Store category in MediaItem for filtering
            media_item.category = metadata_category
            await db.flush()

            uploaded.append({
                "id": media_item.id,
                "filename": safe_name,
                "original_name": orig,
                "size_mb": round(file_size / 1024 / 1024, 2),
                "category": metadata_category,
            })

        uploaded.append({
            "id": media_item.id,
            "filename": safe_name,
            "original_name": orig,
            "size_mb": round(file_size / 1024 / 1024, 2),
        })

    return {
        "success": True,
        "uploaded_count": len(uploaded),
        "error_count": len(errors),
        "uploaded": uploaded,
        "errors": errors,
    }


@router.get("/preview/{media_id}")
async def preview_media(media_id: int, db: AsyncSession = Depends(get_db)):
    """Stream a media file for preview."""
    result = await db.execute(select(MediaItem).where(MediaItem.id == media_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Media tidak ditemukan")

    file_path = Path(item.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File tidak ditemukan di disk")

    # MIME type
    mime_map = {
        ".mp4": "video/mp4", ".webm": "video/webm", ".mkv": "video/x-matroska",
        ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg", ".flac": "audio/flac",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp",
    }
    mime = item.mime or mime_map.get(file_path.suffix.lower(), "application/octet-stream")

    return FileResponse(path=str(file_path), media_type=mime, filename=item.original_name or item.filename)


@router.get("/download/{media_id}")
async def download_media(media_id: int, db: AsyncSession = Depends(get_db)):
    """Download a media file."""
    result = await db.execute(select(MediaItem).where(MediaItem.id == media_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Media tidak ditemukan")

    file_path = Path(item.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File tidak ditemukan di disk")

    return FileResponse(
        path=str(file_path),
        filename=item.original_name or item.filename,
        headers={"Content-Disposition": f"attachment; filename={item.original_name or item.filename}"},
    )


@router.delete("/group/{group}")
async def delete_group(
    group: str,
    channel_id: int = Query(...),
    category: Optional[str] = Query(None, description="Filter metadata by category (title_bank, description_bank, tag_bank, playlist_bank)"),
    db: AsyncSession = Depends(get_db),
):
    """Delete all media items in a group for a channel. For metadata, optionally filter by category."""
    if group not in ALLOWED_GROUPS:
        raise HTTPException(status_code=400, detail="Group tidak valid")

    # Special handling for metadata group
    if group == "metadata":
        from app.models.metadata import MetadataTitlePool, MetadataDescriptionPool, MetadataTagPool, MetadataPlaylistPool

        deleted_rows = 0

        # If category specified, only delete from that specific pool + MediaItems
        if category:
            # Delete from specific pool table
            if category == "title_bank":
                result = await db.execute(select(MetadataTitlePool).where(MetadataTitlePool.channel_id == channel_id))
                for t in result.scalars().all():
                    await db.delete(t)
                    deleted_rows += 1
            elif category == "description_bank":
                result = await db.execute(select(MetadataDescriptionPool).where(MetadataDescriptionPool.channel_id == channel_id))
                for d in result.scalars().all():
                    await db.delete(d)
                    deleted_rows += 1
            elif category == "tag_bank":
                result = await db.execute(select(MetadataTagPool).where(MetadataTagPool.channel_id == channel_id))
                for tg in result.scalars().all():
                    await db.delete(tg)
                    deleted_rows += 1
            elif category == "playlist_bank":
                result = await db.execute(select(MetadataPlaylistPool).where(MetadataPlaylistPool.channel_id == channel_id))
                for pl in result.scalars().all():
                    await db.delete(pl)
                    deleted_rows += 1

            # Delete MediaItems with matching category
            media_result = await db.execute(
                select(MediaItem).where(
                    MediaItem.channel_id == channel_id,
                    MediaItem.asset_type == "metadata",
                    MediaItem.category == category,
                )
            )
            deleted_files = 0
            for item in media_result.scalars().all():
                if storage.delete_file(item.file_path):
                    deleted_files += 1
                await db.delete(item)
                deleted_rows += 1

            return {"success": True, "deleted_files": deleted_files, "deleted_rows": deleted_rows, "category": category}

        # No category specified - delete ALL metadata
        # Delete all pool tables
        title_result = await db.execute(select(MetadataTitlePool).where(MetadataTitlePool.channel_id == channel_id))
        for t in title_result.scalars().all():
            await db.delete(t)
            deleted_rows += 1

        desc_result = await db.execute(select(MetadataDescriptionPool).where(MetadataDescriptionPool.channel_id == channel_id))
        for d in desc_result.scalars().all():
            await db.delete(d)
            deleted_rows += 1

        tag_result = await db.execute(select(MetadataTagPool).where(MetadataTagPool.channel_id == channel_id))
        for tg in tag_result.scalars().all():
            await db.delete(tg)
            deleted_rows += 1

        playlist_result = await db.execute(select(MetadataPlaylistPool).where(MetadataPlaylistPool.channel_id == channel_id))
        for pl in playlist_result.scalars().all():
            await db.delete(pl)
            deleted_rows += 1

        # Delete all MediaItems with asset_type=metadata
        media_result = await db.execute(
            select(MediaItem).where(
                MediaItem.channel_id == channel_id,
                MediaItem.asset_type == "metadata",
            )
        )
        deleted_files = 0
        for item in media_result.scalars().all():
            if storage.delete_file(item.file_path):
                deleted_files += 1
            await db.delete(item)
            deleted_rows += 1

        return {"success": True, "deleted_files": deleted_files, "deleted_rows": deleted_rows}

    # Regular handling for other groups
    result = await db.execute(
        select(MediaItem).where(
            MediaItem.channel_id == channel_id,
            MediaItem.asset_type == group,
        )
    )
    items = result.scalars().all()

    deleted_files = 0
    for item in items:
        if storage.delete_file(item.file_path):
            deleted_files += 1
        await db.delete(item)

    return {"success": True, "deleted_files": deleted_files, "deleted_rows": len(items)}


@router.delete("/{media_id}")
async def delete_media(media_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a single media item. Supports both integer IDs and metadata string IDs."""
    # Handle metadata string IDs (e.g., "title_196", "desc_42", "tag_7", "playlist_5")
    if "_" in str(media_id):
        from app.models.metadata import MetadataTitlePool, MetadataDescriptionPool, MetadataTagPool, MetadataPlaylistPool, MetadataPlaylistPool

        parts = str(media_id).split("_", 1)
        prefix = parts[0]
        try:
            real_id = int(parts[1])
        except (ValueError, IndexError):
            raise HTTPException(status_code=400, detail="ID tidak valid")

        if prefix == "title":
            result = await db.execute(select(MetadataTitlePool).where(MetadataTitlePool.id == real_id))
            item = result.scalar_one_or_none()
            if not item:
                raise HTTPException(status_code=404, detail="Metadata title tidak ditemukan")
            await db.delete(item)
            return {"success": True, "group": "metadata", "category": "title_bank"}

        elif prefix == "desc":
            result = await db.execute(select(MetadataDescriptionPool).where(MetadataDescriptionPool.id == real_id))
            item = result.scalar_one_or_none()
            if not item:
                raise HTTPException(status_code=404, detail="Metadata description tidak ditemukan")
            await db.delete(item)
            return {"success": True, "group": "metadata", "category": "description_bank"}

        elif prefix == "tag":
            result = await db.execute(select(MetadataTagPool).where(MetadataTagPool.id == real_id))
            item = result.scalar_one_or_none()
            if not item:
                raise HTTPException(status_code=404, detail="Metadata tag tidak ditemukan")
            await db.delete(item)
            return {"success": True, "group": "metadata", "category": "tag_bank"}

        elif prefix == "playlist":
            result = await db.execute(select(MetadataPlaylistPool).where(MetadataPlaylistPool.id == real_id))
            item = result.scalar_one_or_none()
            if not item:
                raise HTTPException(status_code=404, detail="Metadata playlist tidak ditemukan")
            await db.delete(item)
            return {"success": True, "group": "metadata", "category": "playlist_bank"}

        else:
            raise HTTPException(status_code=400, detail="Prefix metadata tidak dikenal")

    # Handle regular integer IDs
    try:
        int_id = int(media_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="ID tidak valid")

    result = await db.execute(select(MediaItem).where(MediaItem.id == int_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Media tidak ditemukan")

    storage.delete_file(item.file_path)
    group = item.asset_type or "video"
    await db.delete(item)
    return {"success": True, "group": group}

@router.get('/preview-page/{media_id}', response_class=HTMLResponse)
async def preview_page(request: Request, media_id: int, db: AsyncSession = Depends(get_db)):
    """Preview page with embedded video player."""
    result = await db.execute(select(MediaItem).where(MediaItem.id == media_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail='Media tidak ditemukan')
    
    file_path = Path(item.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail='File tidak ditemukan di disk')
    
    # Determine media type
    mime_map = {
        '.mp4': 'video/mp4', '.webm': 'video/webm', '.mkv': 'video/x-matroska',
        '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.ogg': 'audio/ogg',
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.gif': 'image/gif', '.webp': 'image/webp',
    }
    ext = file_path.suffix.lower()
    mime = item.mime or mime_map.get(ext, 'application/octet-stream')
    is_video = mime.startswith('video/')
    is_audio = mime.startswith('audio/')
    is_image = mime.startswith('image/')
    
    filename = item.original_name or item.filename
    size_mb = round(item.file_size / 1024 / 1024, 2) if item.file_size else 0
    
    media_tag = ''
    if is_video:
        media_tag = f"<video controls autoplay><source src='/api/media/preview-clip/{media_id}' type='{mime}'></video>"
    elif is_audio:
        media_tag = f"<audio controls autoplay><source src='/api/media/preview-clip/{media_id}' type='{mime}'></audio>"
    elif is_image:
        media_tag = f"<img src='/api/media/preview-clip/{media_id}' alt='{filename}'>"
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Preview: {filename}</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ background: #0f172a; color: #e2e8f0; font-family: 'Inter', sans-serif; min-height: 100vh; }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
        .header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; }}
        .title {{ font-size: 18px; font-weight: 700; }}
        .filename {{ font-size: 13px; color: #94a3b8; margin-top: 4px; }}
        .back-btn {{ padding: 10px 20px; border-radius: 10px; background: #1e293b; color: #e2e8f0; text-decoration: none; font-weight: 600; font-size: 13px; border: 1px solid #334155; }}
        .back-btn:hover {{ background: #334155; }}
        .media-container {{ background: #1e293b; border-radius: 16px; overflow: hidden; box-shadow: 0 25px 50px -12px rgba(0,0,0,.5); }}
        video, audio, img {{ width: 100%; display: block; }}
        video {{ max-height: 80vh; background: #000; }}
        .info {{ padding: 20px; border-top: 1px solid #334155; }}
        .info-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }}
        .info-item {{ background: #0f172a; padding: 16px; border-radius: 12px; }}
        .info-label {{ font-size: 11px; color: #64748b; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; }}
        .info-value {{ font-size: 18px; font-weight: 800; margin-top: 6px; }}
        .actions {{ display: flex; gap: 12px; margin-top: 20px; }}
        .btn {{ padding: 12px 24px; border-radius: 10px; font-weight: 700; font-size: 13px; text-decoration: none; cursor: pointer; border: none; }}
        .btn-primary {{ background: linear-gradient(135deg, #2563eb, #7c3aed); color: #fff; }}
        .btn-ghost {{ background: #1e293b; color: #e2e8f0; border: 1px solid #334155; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <div class="title">🎬 Preview</div>
                <div class="filename">{filename}</div>
            </div>
            <a href="/media" class="back-btn">← Kembali</a>
        </div>
        <div class="media-container">
            {media_tag}
            <div class="info">
                <div class="info-grid">
                    <div class="info-item">
                        <div class="info-label">File Name</div>
                        <div class="info-value" style="font-size:14px">{filename}</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">Type</div>
                        <div class="info-value">{mime.split('/')[1].upper()}</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">Size</div>
                        <div class="info-value">{size_mb} MB</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">Asset Type</div>
                        <div class="info-value">{item.asset_type}</div>
                    </div>
                </div>
                <div class="actions">
                    <a href="/api/media/download/{media_id}" class="btn btn-primary">⬇️ Download</a>
                    <button onclick="window.location.reload()" class="btn btn-ghost">🔄 Refresh</button>
                </div>
            </div>
        </div>
    </div>
</body>
</html>'''
    return html

@router.get('/stream/{media_id}')
async def stream_media(request: Request, media_id: int, db: AsyncSession = Depends(get_db)):
    """Stream media file with range request support for video playback."""
    result = await db.execute(select(MediaItem).where(MediaItem.id == media_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail='Media tidak ditemukan')
    
    file_path = Path(item.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail='File tidak ditemukan di disk')
    
    # MIME type
    mime_map = {
        '.mp4': 'video/mp4', '.webm': 'video/webm', '.mkv': 'video/x-matroska',
        '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.ogg': 'audio/ogg', '.flac': 'audio/flac',
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.gif': 'image/gif', '.webp': 'image/webp',
    }
    mime = item.mime or mime_map.get(file_path.suffix.lower(), 'application/octet-stream')
    
    file_size = file_path.stat().st_size
    
    # Check for range request
    range_header = request.headers.get('range')
    
    if range_header:
        # Parse range header
        range_spec = range_header.strip().lower()
        if range_spec.startswith('bytes='):
            range_spec = range_spec[6:]
        
        # Handle range like "0-" or "0-1023"
        if '-' in range_spec:
            start_str, end_str = range_spec.split('-', 1)
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else file_size - 1
            
            # Clamp end to file size
            end = min(end, file_size - 1)
            
            # Calculate content length
            content_length = end - start + 1
            
            # Create streaming response
            def file_iterator():
                with open(file_path, 'rb') as f:
                    f.seek(start)
                    remaining = content_length
                    chunk_size = 8192
                    while remaining > 0:
                        read_size = min(chunk_size, remaining)
                        chunk = f.read(read_size)
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        yield chunk
            
            headers = {
                'Content-Range': f'bytes {start}-{end}/{file_size}',
                'Accept-Ranges': 'bytes',
                'Content-Length': str(content_length),
                'Content-Type': mime,
            }
            
            return StreamingResponse(
                file_iterator(),
                status_code=206,
                headers=headers,
                media_type=mime,
            )
    
    # No range request - return full file
    return FileResponse(
        path=str(file_path),
        media_type=mime,
        headers={
            'Accept-Ranges': 'bytes',
            'Content-Length': str(file_size),
        },
    )

@router.get('/preview-clip/{media_id}')
async def preview_clip(media_id: int, db: AsyncSession = Depends(get_db)):
    """Generate and serve a short preview clip (first20 seconds)."""
    import subprocess
    import hashlib
    
    result = await db.execute(select(MediaItem).where(MediaItem.id == media_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail='Media tidak ditemukan')
    
    file_path = Path(item.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail='File tidak ditemukan di disk')
    
    # Check if it's a video
    ext = file_path.suffix.lower()
    if ext not in ['.mp4', '.mkv', '.avi', '.mov', '.webm']:
        raise HTTPException(status_code=400, detail='File bukan video')
    
    # Create preview cache directory
    cache_dir = Path('/app/storage/previews')
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate cache filename based on original file
    file_hash = hashlib.md5(str(file_path).encode()).hexdigest()[:12]
    preview_filename = f'preview_{media_id}_{file_hash}.mp4'
    preview_path = cache_dir / preview_filename
    
    # Check if preview already exists
    if not preview_path.exists():
        # Create preview clip (first20 seconds, low quality for speed)
        cmd = [
            'ffmpeg', '-y',
            '-i', str(file_path),
            '-t', '20',
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-crf', '28',
            '-c:a', 'aac',
            '-b:a', '64k',
            '-movflags', '+faststart',
            '-vf', 'scale=640:-2',
            str(preview_path),
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=60)
            if result.returncode != 0:
                raise HTTPException(status_code=500, detail='Gagal membuat preview')
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=500, detail='Timeout membuat preview')
    
    # Serve the preview clip
    if not preview_path.exists():
        raise HTTPException(status_code=500, detail='Preview tidak tersedia')
    
    return FileResponse(
        path=str(preview_path),
        media_type='video/mp4',
        headers={
            'Accept-Ranges': 'bytes',
            'Cache-Control': 'public, max-age=3600',
        },
    )
