#!/usr/bin/env python3
"""
Upload Worker - JB APUL v3
Polls database for pending upload items and uploads to YouTube.
"""

import json
import os
import sys
import time
import logging
from pathlib import Path
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

# Config
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://jb_user:change-me@db:5432/jb_apulv3")
STORAGE_PATH = os.environ.get("STORAGE_PATH", "/app/storage")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "10"))
MAX_RETRIES = 3

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [UPLOAD] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("upload")

DB_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

def sanitize_tag(tag: str) -> str:
    """Sanitize a single tag for YouTube."""
    import re
    # Remove special characters that YouTube doesn't accept
    # Remove characters that YouTube doesn't accept in tags
    for char in ['<', '>', '"', "'", '&']:
        tag = tag.replace(char, '')
    # Remove extra whitespace
    tag = ' '.join(tag.split())
    # Truncate to 30 chars
    tag = tag[:30]
    return tag.strip()

def truncate_tags(tags_str: str, max_total: int = 500, max_per_tag: int = 30) -> str:
    """Truncate tags to fit YouTube limits."""
    if not tags_str:
        return ""
    # Split and sanitize each tag
    raw_tags = [t.strip() for t in tags_str.split(",") if t.strip()]
    sanitized = []
    seen = set()
    for t in raw_tags:
        clean = sanitize_tag(t)
        if clean and len(clean) >= 2 and clean.lower() not in seen:
            seen.add(clean.lower())
            sanitized.append(clean)
    # Truncate to fit YouTube limits
    result = []
    total = 0
    for t in sanitized:
        tag_len = len(t)
        if total + tag_len + (2 if result else 0) > max_total:
            break
        if len(result) >= 30:  # YouTube max 30 tags
            break
        result.append(t)
        total += tag_len + (2 if result else 0)
    return ", ".join(result)



def get_db():
    return psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def log_to_file(message: str):
    log_path = Path(STORAGE_PATH) / "logs" / "upload_worker.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(str(message) + "\n")


def classify_error(msg: str) -> tuple:
    if "uploadLimitExceeded" in msg or "exceeded the number of videos" in msg:
        return (True, "YouTube upload limit tercapai. Tunggu 24 jam.")
    if "quotaExceeded" in msg:
        return (True, "YouTube API quota habis.")
    if "token" in msg.lower() or "OAuth" in msg:
        return (True, "Token Google expired. Re-login.")
    if "No such file" in msg or "not found" in msg:
        return (True, "File video tidak ditemukan.")
    lower = msg.lower()
    if any(kw in lower for kw in ["network", "timeout", "connection", "500", "502", "503", "504"]):
        return (False, "Gagal sementara. Auto-retry...")
    return (True, msg)


def poll_pending_items():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM upload_batch_items WHERE status = 'pending' ORDER BY id ASC LIMIT 1")
            return cur.fetchone()
    finally:
        conn.close()


def get_item(item_id: int) -> dict:
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM upload_batch_items WHERE id=%s", (item_id,))
            return cur.fetchone()
    finally:
        conn.close()


def update_item(item_id: int, **kwargs):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            sets = ", ".join(f"{k} = %s" for k in kwargs)
            values = list(kwargs.values()) + [item_id]
            cur.execute(f"UPDATE upload_batch_items SET {sets}, updated_at=NOW() WHERE id = %s", values)
            conn.commit()
    finally:
        conn.close()


def update_batch(batch_id: int, **kwargs):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            sets = ", ".join(f"{k} = %s" for k in kwargs)
            values = list(kwargs.values()) + [batch_id]
            cur.execute(f"UPDATE upload_batches SET {sets} WHERE id = %s", values)
            conn.commit()
    finally:
        conn.close()


def get_channel(channel_id: int) -> dict:
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM channels WHERE id=%s", (channel_id,))
            return cur.fetchone()
    finally:
        conn.close()


def upload_to_youtube(item: dict, channel: dict) -> dict:
    import httplib2
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.oauth2.credentials import Credentials

    # Find the file path
    source_path = item.get("source_path", "")
    if not source_path:
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT file_path FROM media_items WHERE channel_id=%s AND asset_type='upload_ready' ORDER BY id DESC LIMIT 1", (item["channel_id"],))
                row = cur.fetchone()
                if row:
                    source_path = row["file_path"]
        finally:
            conn.close()

    if not source_path:
        return {"success": False, "error": "File video tidak ditemukan"}

    # Resolve absolute path
    if source_path.startswith("/"):
        abs_path = source_path
    else:
        abs_path = os.path.join(STORAGE_PATH, source_path.lstrip("/"))

    if not os.path.exists(abs_path):
        return {"success": False, "error": f"File tidak ditemukan: {abs_path}"}

    # Get Google credentials
    access_token = channel.get("access_token", "")
    refresh_token = channel.get("refresh_token", "")

    if not access_token:
        return {"success": False, "error": "Google access token tidak ada"}

    # Build credentials
    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
        client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
    )

    # Refresh token if expired
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(httplib2.Http())
            conn = get_db()
            try:
                with conn.cursor() as cur:
                    cur.execute("UPDATE channels SET access_token=%s WHERE id=%s", (creds.token, channel["id"]))
                    conn.commit()
            finally:
                conn.close()
        except Exception as e:
            return {"success": False, "error": f"Token refresh gagal: {str(e)}"}

    # Build YouTube service
    youtube = build("youtube", "v3", credentials=creds)

    # Prepare video metadata
    title = (item.get("title") or "Untitled")[:100]
    description = (item.get("description") or "")[:5000]
    tags_str = truncate_tags(item.get("tags") or "")
    tag_list = [t.strip() for t in tags_str.split(",") if t.strip()]
    log.info(f"Tags debug: count={len(tag_list)}, total_chars={sum(len(t) for t in tag_list)}, tags={tag_list[:5]}...")
    visibility = item.get("visibility", "private")
    scheduled_at = item.get("scheduled_at")

    # Set privacy
    privacy_status = "private" if visibility == "scheduled" else visibility

    # Build video body
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tag_list,
            "categoryId": "10",
        },
        "status": {
            "privacyStatus": privacy_status,
            "madeForKids": False,
            "selfDeclaredMadeForKids": False,
        },
    }

    # Set scheduled publish time
    if visibility == "scheduled" and scheduled_at:
        try:
            from datetime import datetime
            # Handle both string and datetime objects
            if isinstance(scheduled_at, str):
                from dateutil import parser as date_parser
                dt = date_parser.parse(scheduled_at)
            else:
                dt = scheduled_at  # Already a datetime object
            body["status"]["publishAt"] = dt.isoformat()
            log.info(f"Scheduled publishAt: {dt.isoformat()}")
        except Exception as e:
            log.error(f"Error parsing scheduled_at: {e}")

    # Find thumbnail (optional) - use specific one first, then random from pool
    thumbnail_path = ""
    if item.get("thumbnail_path"):
        thumb_abs = item["thumbnail_path"] if item["thumbnail_path"].startswith("/") else os.path.join(STORAGE_PATH, item["thumbnail_path"].lstrip("/"))
        if os.path.exists(thumb_abs):
            thumbnail_path = thumb_abs
            log.info(f"Using specific thumbnail: {thumbnail_path}")
    if not thumbnail_path:
        conn_thumb = get_db()
        try:
            with conn_thumb.cursor() as cur:
                cur.execute("SELECT file_path FROM media_items WHERE channel_id=%s AND asset_type='thumbnail' ORDER BY RANDOM() LIMIT 1", (item["channel_id"],))
                thumb = cur.fetchone()
                if thumb and thumb["file_path"]:
                    thumb_abs = thumb["file_path"] if thumb["file_path"].startswith("/") else os.path.join(STORAGE_PATH, thumb["file_path"].lstrip("/"))
                    if os.path.exists(thumb_abs):
                        thumbnail_path = thumb_abs
                        log.info(f"Using random thumbnail from pool: {thumbnail_path}")
        finally:
            conn_thumb.close()

    # Upload video
    try:
        file_size = os.path.getsize(abs_path)
        log.info(f"Uploading {title} ({file_size / 1024 / 1024:.1f} MB)")

        media = MediaFileUpload(abs_path, mimetype="video/mp4", resumable=True, chunksize=10*1024*1024)
        request = youtube.videos().insert(part=",".join(body.keys()), body=body, media_body=media)

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                log.info(f"Upload progress: {pct}%")
                update_item(item["id"], progress=pct)

        video_id = response.get("id", "")
        log.info(f"Upload berhasil! Video ID: {video_id}")

        # Upload thumbnail if available
        if thumbnail_path and video_id:
            try:
                log.info(f"Uploading thumbnail: {thumbnail_path}")
                thumb_media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
                youtube.thumbnails().set(videoId=video_id, media_body=thumb_media).execute()
                log.info("Thumbnail uploaded successfully")
            except Exception as e:
                log.warning(f"Thumbnail upload failed (non-fatal): {e}")

        update_item(item["id"], progress=100)
        return {"success": True, "video_id": video_id}

    except Exception as e:
        log.error(f"Upload gagal: {str(e)}")
        return {"success": False, "error": str(e)}


def process_item(item_id: int):
    log.info(f"[UPLOAD] Processing item {item_id}")
    log_to_file(f"[UPLOAD] Processing item {item_id}")

    item = get_item(item_id)
    if not item or item["status"] != "pending":
        return

    # Update status to processing
    update_item(item_id, status="processing")

    # Update batch
    batch_id = item.get("upload_batch_id")
    if batch_id:
        update_batch(batch_id, status="processing")

    # Get channel
    channel = get_channel(item["channel_id"])
    if not channel:
        update_item(item_id, status="failed", last_error="Channel tidak ditemukan")
        return

    # Upload to YouTube
    result = upload_to_youtube(item, channel)

    if result["success"]:
        update_item(item_id,
            status="done",
            youtube_video_id=result.get("video_id", ""),
            finished_at=datetime.now(timezone.utc),
        )
        log.info(f"[UPLOAD] Item {item_id} DONE - Video ID: {result.get('video_id')}")

        # Update batch success count
        if batch_id:
            conn = get_db()
            try:
                with conn.cursor() as cur:
                    cur.execute("UPDATE upload_batches SET success_count = COALESCE(success_count,0) + 1 WHERE id=%s", (batch_id,))
                    conn.commit()
                    cur.execute("SELECT COUNT(*) as cnt FROM upload_batch_items WHERE upload_batch_id=%s AND status='pending'", (batch_id,))
                    remaining = cur.fetchone()["cnt"]
                    if remaining == 0:
                        update_batch(batch_id, status="done", finished_at=datetime.now(timezone.utc))
            finally:
                conn.close()
    else:
        error_msg = result.get("error", "Unknown error")
        is_permanent, human_msg = classify_error(error_msg)

        if not is_permanent:
            update_item(item_id, status="pending", last_error=human_msg)
            log.warning(f"[UPLOAD] Item {item_id} retryable, will retry")
        else:
            update_item(item_id, status="failed", last_error=human_msg, finished_at=datetime.now(timezone.utc))
            log.error(f"[UPLOAD] Item {item_id} FAILED: {human_msg}")

            if batch_id:
                conn = get_db()
                try:
                    with conn.cursor() as cur:
                        cur.execute("UPDATE upload_batches SET failed_count = COALESCE(failed_count,0) + 1, last_error=%s WHERE id=%s", (human_msg, batch_id))
                        conn.commit()
                finally:
                    conn.close()


def main():
    log.info("=" * 50)
    log.info("Upload Worker v3 STARTED")
    log.info(f"Storage: {STORAGE_PATH}")
    log.info(f"Poll interval: {POLL_INTERVAL}s")
    log.info("=" * 50)

    while True:
        try:
            row = poll_pending_items()
            if not row:
                time.sleep(POLL_INTERVAL)
                continue

            process_item(row["id"])
            time.sleep(1)

        except psycopg2.OperationalError as e:
            log.error(f"Database error: {e}")
            time.sleep(10)
        except Exception as e:
            log.error(f"Error: {e}", exc_info=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
