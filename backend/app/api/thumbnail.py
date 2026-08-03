"""
Thumbnail Generator — JB APUL v3
Generate thumbnails using Pollinations.ai (free, no API key)
"""

import os
import logging
import httpx
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.db.session import get_db

router = APIRouter()
log = logging.getLogger("thumbnail")

STORAGE_PATH = "/app/storage"


@router.post("/generate")
async def generate_thumbnail(data: dict, db: AsyncSession = Depends(get_db)):
    """
    Generate a thumbnail using Pollinations.ai (free).

    Body: {
        "channel_id": 1,
        "filename": "video_id_abc",
        "prompt": "underwater coral reef, vibrant colors, 4K..."
    }

    Returns: {
        "success": true,
        "image_url": "/storage/thumbnails/channel_1/video_id_abc.jpg",
        "pollinations_url": "https://image.pollinations.ai/..."
    }
    """
    channel_id = data.get("channel_id")
    filename = data.get("filename", "thumbnail")
    prompt = data.get("prompt", "")

    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt required")

    # Enhance prompt for YouTube thumbnail
    enhanced_prompt = (
        f"YouTube thumbnail, {prompt}, "
        "vibrant colors, eye-catching, professional quality, "
        "4K ultra detailed, bold minimal text, cinematic lighting"
    )

    # Pollinations.ai URL
    import urllib.parse
    encoded_prompt = urllib.parse.quote(enhanced_prompt)
    pollinations_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1280&height=720&nologo=true"

    # Save to storage
    thumb_dir = os.path.join(STORAGE_PATH, f"thumbnails/channel_{channel_id}")
    os.makedirs(thumb_dir, exist_ok=True)

    # Clean filename
    safe_name = "".join(c for c in filename if c.isalnum() or c in "-_")[:50]
    output_path = os.path.join(thumb_dir, f"{safe_name}.jpg")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(pollinations_url, follow_redirects=True)

            if resp.status_code == 200 and len(resp.content) > 1000:
                with open(output_path, "wb") as f:
                    f.write(resp.content)

                # Save to ai_fixes for tracking
                from app.models.channel import Channel
                result = await db.execute(select(Channel).where(Channel.id == channel_id))
                channel = result.scalar_one_or_none()

                relative_path = f"thumbnails/channel_{channel_id}/{safe_name}.jpg"

                return {
                    "success": True,
                    "image_url": f"/storage/{relative_path}",
                    "filename": f"{safe_name}.jpg",
                    "size_kb": round(len(resp.content) / 1024, 1),
                    "prompt_used": enhanced_prompt,
                }
            else:
                return {
                    "success": False,
                    "error": f"Image generation failed: HTTP {resp.status_code}",
                }

    except httpx.TimeoutException:
        return {"success": False, "error": "Timeout — Pollinations.ai took too long"}
    except Exception as e:
        log.error(f"Thumbnail generation error: {e}")
        return {"success": False, "error": str(e)[:200]}


@router.get("/list/{channel_id}")
async def list_thumbnails(channel_id: int):
    """List generated thumbnails for a channel."""
    thumb_dir = os.path.join(STORAGE_PATH, f"thumbnails/channel_{channel_id}")

    if not os.path.exists(thumb_dir):
        return {"success": True, "thumbnails": []}

    files = []
    for f in sorted(os.listdir(thumb_dir), reverse=True):
        if f.endswith(('.jpg', '.png', '.webp')):
            filepath = os.path.join(thumb_dir, f)
            files.append({
                "filename": f,
                "url": f"/storage/thumbnails/channel_{channel_id}/{f}",
                "size_kb": round(os.path.getsize(filepath) / 1024, 1),
                "created_at": datetime.fromtimestamp(os.path.getctime(filepath)).isoformat(),
            })

    return {"success": True, "thumbnails": files}
