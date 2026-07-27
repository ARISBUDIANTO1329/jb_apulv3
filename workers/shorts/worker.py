#!/usr/bin/env python3
"""
Shorts Worker - Auto-generate and upload shorts from completed long videos.
Triggers automatically when a long video upload completes and has a YouTube link.
"""

import os
import sys
import time
import subprocess
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta

import psycopg2
import psycopg2.extras

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

# Config
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://jb_user:change-me@db:5432/jb_apulv3")
STORAGE_PATH = os.environ.get("STORAGE_PATH", "/app/storage")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "10"))
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")

# Shorts configuration - descending durations for variety
SHORT_COUNT = 3
SHORT_DURATIONS = [60, 45, 30]  # seconds: 60s, 45s, 30s
SCHEDULE_INTERVAL_HOURS = 1

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SHORTS] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("shorts")

DB_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


def get_db():
    return psycopg2.connect(DB_URL)


def get_youtube_client(channel_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT access_token, refresh_token, token_expires_at "
        "FROM channels WHERE id = %s",
        (channel_id,),
    )
    channel = cur.fetchone()
    cur.close()
    conn.close()

    if not channel or not channel["access_token"]:
        return None

    creds = Credentials(
        token=channel["access_token"],
        refresh_token=channel["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
    )

    if channel["token_expires_at"]:
        expiry = channel["token_expires_at"]
        if isinstance(expiry, str):
            expiry = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
        creds.expiry = expiry

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE channels SET access_token = %s, token_expires_at = %s WHERE id = %s",
            (creds.token, creds.expiry, channel_id),
        )
        conn.commit()
        cur.close()
        conn.close()

    return build("youtube", "v3", credentials=creds)


def find_completed_uploads():
    """Find uploads that are done with a YouTube link but no shorts job yet."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """
        SELECT ubi.*, ub.channel_id, ub.name as batch_name
        FROM upload_batch_items ubi
        JOIN upload_batches ub ON ubi.upload_batch_id = ub.id
        WHERE ubi.status = 'done'
          AND ubi.youtube_video_id IS NOT NULL
          AND ubi.youtube_video_id != ''
          AND NOT EXISTS (
              SELECT 1 FROM shorts_jobs sj WHERE sj.long_upload_id = ubi.id
          )
        ORDER BY ubi.finished_at DESC
        LIMIT 5
        """
    )
    uploads = cur.fetchall()
    cur.close()
    conn.close()
    return uploads


def create_shorts_job(upload_item):
    """Create a shorts job + items with descending durations and scheduled times."""
    conn = get_db()
    cur = conn.cursor()

    long_url = "https://www.youtube.com/watch?v=" + upload_item["youtube_video_id"]
    long_title = upload_item.get("title") or "Untitled"

    cur.execute(
        """
        INSERT INTO shorts_jobs (
            channel_id, long_upload_id, long_youtube_url, long_title,
            short_count, short_duration, segment_mode, status, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
        RETURNING id
        """,
        (
            upload_item["channel_id"],
            upload_item["id"],
            long_url,
            long_title,
            SHORT_COUNT,
            SHORT_DURATIONS[0],
            "auto",
            "pending",
        ),
    )
    job_id = cur.fetchone()[0]

    now = datetime.now(timezone.utc)
    description = "Watch full video here: " + long_url

    # Calculate start/end times for each short
    current_second = 0
    for i in range(SHORT_COUNT):
        duration = SHORT_DURATIONS[i] if i < len(SHORT_DURATIONS) else SHORT_DURATIONS[-1]
        start_second = current_second
        end_second = current_second + duration
        current_second = end_second

        # Schedule time: 1 hour, 2 hours, 3 hours from now
        scheduled_time = now + timedelta(hours=(i + 1) * SCHEDULE_INTERVAL_HOURS)
        upload_time_str = scheduled_time.strftime("%H:%M")

        cur.execute(
            """
            INSERT INTO shorts_items (
                job_id, short_number, title, description,
                start_second, end_second, upload_time, status, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """,
            (
                job_id,
                i + 1,
                long_title + " - Part " + str(i + 1),
                description,
                start_second,
                end_second,
                upload_time_str,
                "pending",
            ),
        )

    conn.commit()
    cur.close()
    conn.close()

    log.info("Created shorts job #%s for upload #%s (%d shorts: %s)", job_id, upload_item["id"], SHORT_COUNT, SHORT_DURATIONS)
    return job_id


def get_pending_jobs():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """
        SELECT sj.*, ubi.youtube_video_id, ubi.title as long_title, c.name as channel_name
        FROM shorts_jobs sj
        JOIN upload_batch_items ubi ON sj.long_upload_id = ubi.id
        JOIN channels c ON sj.channel_id = c.id
        WHERE sj.status = 'pending'
        ORDER BY sj.created_at ASC
        LIMIT 3
        """
    )
    jobs = cur.fetchall()
    cur.close()
    conn.close()
    return jobs


def get_shorts_items(job_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT * FROM shorts_items WHERE job_id = %s ORDER BY short_number ASC",
        (job_id,),
    )
    items = cur.fetchall()
    cur.close()
    conn.close()
    return items


def update_job_status(job_id, status, error_msg=None):
    conn = get_db()
    cur = conn.cursor()
    if error_msg:
        cur.execute(
            "UPDATE shorts_jobs SET status = %s, error_message = %s, updated_at = NOW() WHERE id = %s",
            (status, error_msg, job_id),
        )
    else:
        cur.execute(
            "UPDATE shorts_jobs SET status = %s, updated_at = NOW() WHERE id = %s",
            (status, job_id),
        )
    conn.commit()
    cur.close()
    conn.close()


def update_item_status(item_id, status, youtube_id=None, error_msg=None):
    conn = get_db()
    cur = conn.cursor()
    if youtube_id:
        cur.execute(
            "UPDATE shorts_items SET status = %s, youtube_id = %s, uploaded_at = NOW() WHERE id = %s",
            (status, youtube_id, item_id),
        )
    elif error_msg:
        cur.execute(
            "UPDATE shorts_items SET status = %s, error_message = %s WHERE id = %s",
            (status, error_msg, item_id),
        )
    else:
        cur.execute(
            "UPDATE shorts_items SET status = %s WHERE id = %s",
            (status, item_id),
        )
    conn.commit()
    cur.close()
    conn.close()


def download_video(youtube_id, output_path):
    url = "https://www.youtube.com/watch?v=" + youtube_id
    cmd = [
        "yt-dlp",
        "-f", "best[height<=1080]",
        "--merge-output-format", "mp4",
        "-o", output_path,
        url,
    ]
    log.info("Downloading %s", url)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception("yt-dlp failed: " + result.stderr)
    return output_path


def split_video(input_path, output_dir, items):
    """Split video into segments based on shorts_items start/end times."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    segments = []

    for item in items:
        start = item["start_second"]
        end = item["end_second"]
        duration = end - start
        short_num = item["short_number"]

        output_path = Path(output_dir) / ("short_" + str(short_num) + ".mp4")

        cmd = [
            "ffmpeg", "-i", input_path,
            "-ss", str(start),
            "-t", str(duration),
            "-c:v", "libx264", "-c:a", "aac",
            "-strict", "experimental", "-y",
            str(output_path),
        ]

        log.info("Creating short %d: %ss to %ss (%ss)", short_num, start, end, duration)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception("ffmpeg failed: " + result.stderr)

        segments.append((item, str(output_path)))

    return segments


def upload_short(youtube_client, video_path, title, description, scheduled_at):
    """Upload a short to YouTube with scheduled publish time."""
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": ["shorts", "shortvideo"],
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False,
        },
    }

    # Add publishAt for scheduled upload
    if scheduled_at:
        if isinstance(scheduled_at, datetime):
            body["status"]["publishAt"] = scheduled_at.strftime("%Y-%m-%dT%H:%M:%S.0Z")
            body["status"]["privacyStatus"] = "private"
        else:
            body["status"]["publishAt"] = str(scheduled_at)
            body["status"]["privacyStatus"] = "private"

    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
    request = youtube_client.videos().insert(part=",".join(body.keys()), body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log.info("Upload progress: %d%%", int(status.progress() * 100))

    return response["id"]


def process_job(job):
    job_id = job["id"]
    youtube_id = job["youtube_video_id"]
    channel_id = job["channel_id"]

    log.info("Processing job #%s for YouTube video %s", job_id, youtube_id)

    try:
        youtube = get_youtube_client(channel_id)
        if not youtube:
            raise Exception("No YouTube credentials for channel " + str(channel_id))

        video_path = Path(STORAGE_PATH) / "shorts" / ("job_" + str(job_id)) / "source.mp4"
        video_path.parent.mkdir(parents=True, exist_ok=True)
        download_video(youtube_id, str(video_path))

        items = get_shorts_items(job_id)

        output_dir = Path(STORAGE_PATH) / "shorts" / ("job_" + str(job_id)) / "segments"
        segments = split_video(str(video_path), str(output_dir), items)

        now = datetime.now(timezone.utc)
        for i, (item, segment_path) in enumerate(segments):
            log.info("Uploading short %d/%d", i + 1, len(segments))

            # Calculate scheduled time based on interval
            scheduled_time = now + timedelta(hours=(i + 1) * SCHEDULE_INTERVAL_HOURS)

            try:
                yt_video_id = upload_short(
                    youtube,
                    segment_path,
                    item["title"],
                    item["description"],
                    scheduled_time,
                )
                update_item_status(item["id"], "done", youtube_id=yt_video_id)
                log.info("Short %d uploaded: %s (scheduled: %s)", i + 1, yt_video_id, scheduled_time)
            except Exception as e:
                log.error("Failed to upload short %d: %s", i + 1, e)
                update_item_status(item["id"], "failed", error_msg=str(e))

        update_job_status(job_id, "done")
        log.info("Job #%s completed", job_id)

    except Exception as e:
        log.error("Job #%s failed: %s", job_id, e)
        update_job_status(job_id, "failed", error_msg=str(e))


def main():
    log.info("Shorts worker started (auto-trigger mode)")
    log.info("Config: %d shorts, durations %s, interval %dh", SHORT_COUNT, SHORT_DURATIONS, SCHEDULE_INTERVAL_HOURS)

    while True:
        try:
            completed = find_completed_uploads()
            for upload in completed:
                log.info("Found completed upload #%s: %s", upload["id"], upload.get("title", "Untitled"))
                create_shorts_job(upload)

            pending = get_pending_jobs()
            for job in pending:
                process_job(job)

        except Exception as e:
            log.error("Error in main loop: %s", e)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
