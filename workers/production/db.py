"""
Database helper for production workers.
Uses psycopg2 (sync) for standalone worker scripts.
"""

import os
import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://jb_user:change-me@db:5432/jb_apulv3",
)

# Convert async URL to sync for psycopg2
DB_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


def get_db():
    """Get a new database connection."""
    return psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def update_progress(job_id: int, progress: int, stage: str):
    """Update progress field in production_jobs for real-time tracking."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE production_jobs SET progress=%s, process_status=%s, updated_at=NOW() WHERE id=%s",
                (progress, stage, job_id),
            )
            conn.commit()
        conn.close()
    except Exception:
        pass


def update_job(job_id: int, **kwargs):
    """Update arbitrary job fields."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            sets = ", ".join(f"{k} = %s" for k in kwargs)
            values = list(kwargs.values()) + [job_id]
            cur.execute(f"UPDATE production_jobs SET {sets}, updated_at=NOW() WHERE id = %s", values)
            conn.commit()
    finally:
        conn.close()


def get_job(job_id: int) -> dict | None:
    """Get a single job by ID."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM production_jobs WHERE id=%s", (job_id,))
            return cur.fetchone()
    finally:
        conn.close()



import json as _json
from datetime import datetime, timezone

def append_log(job_id: int, message: str):
    """Append a log line to process_log JSONB column."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
            entry = _json.dumps({"t": ts, "m": message})
            cur.execute(
                "UPDATE production_jobs SET process_log = process_log || %s::jsonb, updated_at=NOW() WHERE id = %s",
                (entry, job_id),
            )
            conn.commit()
        conn.close()
    except Exception:
        pass

def get_next_pending_job() -> dict | None:
    """Get the next pending production job."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id FROM production_jobs
                WHERE final_status IS NULL
                  AND (process_status IS NULL OR process_status <> 'control_room_inline')
                ORDER BY id ASC LIMIT 1
            """)
            return cur.fetchone()
    finally:
        conn.close()
