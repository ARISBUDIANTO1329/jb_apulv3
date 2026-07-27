#!/usr/bin/env python3
"""
Livestream Worker for JB APUL v3
Polls database for pending/scheduled livestream jobs.
Creates YouTube broadcast via API, then streams video via FFmpeg to RTMP.

FIXED: 2026-07-21
- Added reconnect_counts initialization (was missing → NameError)
- Added startup reconciliation: on restart, verify DB 'running' jobs against live FFmpeg
- Added periodic reconciliation: every 60s cross-check DB vs running_processes
- Strengthened channel conflict check: also queries DB, not just in-memory dict
- Stores actual YouTube stream_key back to DB for audit trail
- Better logging for debugging process lifecycle
"""

import threading
import os
import sys
import time
import signal
import subprocess
import logging
import json
import re
from pathlib import Path
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

import psycopg2
import psycopg2.extras

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

# Config
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://jb_user:change-me@localhost:5433/jb_apulv3")
STORAGE_PATH = os.environ.get("STORAGE_PATH", "/app/storage")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "3"))
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [LIVESTREAM] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("livestream")

# Convert async URL to sync for psycopg2
DB_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

# Track running FFmpeg processes
running_processes = {}  # job_id -> subprocess.Popen
stream_stats_store = {}  # job_id -> {bitrate, fps, drops, speed, time}
reconnect_counts = {}    # job_id -> int  (was missing before!)

# Reconciliation counter
_reconcile_counter = 0
RECONCILE_EVERY = 20  # every ~60s (20 * 3s poll)
MAX_RECONNECTS = 10  # Max reconnection attempts before giving up (increased for 12h streams)
RECONNECT_DELAY = 5  # Seconds to wait before reconnecting

# Graceful shutdown
_shutdown_requested = False

# Health HTTP server port
HEALTH_PORT = 9999


# ── Health HTTP Server ─────────────────────────────────────────

class HealthHandler(BaseHTTPRequestHandler):
    """Minimal HTTP server for health checks from backend."""
    def do_GET(self):
        if self.path == "/health":
            # Return running jobs status
            jobs_status = {}
            for job_id, proc in running_processes.items():
                is_alive = proc.poll() is None
                stats = stream_stats_store.get(job_id, {})
                jobs_status[str(job_id)] = {
                    "alive": is_alive,
                    "pid": proc.pid if hasattr(proc, 'pid') else None,
                    "bitrate": stats.get("bitrate"),
                    "fps": stats.get("fps"),
                    "elapsed": stats.get("elapsed_seconds"),
                    "drops": stats.get("drops"),
                }
            response = json.dumps({
                "status": "ok",
                "running_count": len([j for j in jobs_status.values() if j["alive"]]),
                "jobs": jobs_status,
            })
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(response.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress HTTP logs


def start_health_server():
    """Start health HTTP server in background thread."""
    try:
        server = HTTPServer(("0.0.0.0", HEALTH_PORT), HealthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        log.info(f"[HEALTH] Health server started on port {HEALTH_PORT}")
    except Exception as e:
        log.warning(f"[HEALTH] Failed to start health server: {e}")


# ── Stop Command Handler ───────────────────────────────────────

def check_stop_requests():
    """Check DB for stop_requested flag and stop matching jobs."""
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, channel_id, title, broadcast_id
                FROM live_jobs
                WHERE stop_requested = TRUE AND status = 'running'
            """)
            jobs_to_stop = cur.fetchall()

        for job in jobs_to_stop:
            job_id = job["id"]
            log.info(f"[STOP-CMD] Stop requested for job #{job_id}: {job.get('title', '-')}")

            # Kill FFmpeg if running
            proc = running_processes.get(job_id)
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

            # End YouTube broadcast
            _try_end_broadcast(job)

            # Update DB
            update_job(job_id,
                       status="stopped",
                       stop_requested=False,
                       finished_at=datetime.now(timezone.utc).isoformat(),
                       error_message="Stopped by user request")

            # Cleanup
            running_processes.pop(job_id, None)
            stream_stats_store.pop(job_id, None)
            reconnect_counts.pop(job_id, None)

            log.info(f"[STOP-CMD] Job #{job_id} stopped successfully")

    except Exception as e:
        log.error(f"[STOP-CMD] Error checking stop requests: {e}")
    finally:
        conn.close()


def get_db():
    """Get database connection."""
    return psycopg2.connect(DB_URL)


# ── Reconciliation ─────────────────────────────────────────────

def reconcile_running_jobs():
    """
    Cross-check DB 'running' jobs against actual in-memory running_processes.
    - If DB says running but not in running_processes → check if FFmpeg PID alive, else mark failed/stopped.
    - If in running_processes but DB says not running → kill orphan FFmpeg.
    This prevents stale state after worker restart or FFmpeg crash detection miss.
    """
    log.info("[RECONCILE] Starting reconciliation check...")

    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Get all jobs that DB thinks are running
            cur.execute("""
                SELECT id, channel_id, process_id, broadcast_id, video_source, status
                FROM live_jobs
                WHERE status = 'running'
            """)
            db_running = {row["id"]: dict(row) for row in cur.fetchall()}

        # ── Case 1: DB says running, but NOT in running_processes ──
        for job_id, db_job in db_running.items():
            if job_id in running_processes:
                continue  # already tracked in memory, OK

            pid = db_job["process_id"]
            if not pid:
                log.warning(f"[RECONCILE] Job #{job_id}: DB says running but no process_id → marking failed")
                update_job(job_id, status="failed", error_message="No process ID after reconciliation",
                           finished_at=datetime.now(timezone.utc).isoformat())
                continue

            # Check if the PID is alive (might be reused by OS)
            alive = _is_pid_alive(pid)
            if alive:
                # PID is alive — but is it actually FFmpeg streaming to the right key?
                # Verify by checking /proc/<pid>/cmdline
                cmdline = _get_pid_cmdline(pid)
                if cmdline and "ffmpeg" in cmdline.lower():
                    log.info(f"[RECONCILE] Job #{job_id}: FFmpeg PID {pid} is alive, re-adding to tracking")
                    # We can't re-create the Popen object, but we mark it as tracked
                    # by adding a sentinel. check_running_jobs will handle it via PID check.
                    # For now, just confirm DB status is correct.
                    # We DON'T add to running_processes since we don't have the Popen object.
                    # Instead, we add a lightweight tracker.
                    running_processes[job_id] = _PIDSentinel(pid, job_id)
                else:
                    log.warning(f"[RECONCILE] Job #{job_id}: PID {pid} alive but NOT ffmpeg (cmdline={cmdline}) → marking failed")
                    update_job(job_id, status="failed",
                               error_message=f"PID {pid} reused by non-ffmpeg process",
                               finished_at=datetime.now(timezone.utc).isoformat())
            else:
                log.warning(f"[RECONCILE] Job #{job_id}: FFmpeg PID {pid} is DEAD → marking failed")
                # Try to end the YouTube broadcast
                _try_end_broadcast(db_job)
                update_job(job_id, status="failed",
                           error_message=f"FFmpeg process {pid} died (detected by reconciliation)",
                           finished_at=datetime.now(timezone.utc).isoformat())

        # ── Case 2: In running_processes but DB says not running ──
        for job_id in list(running_processes.keys()):
            if job_id not in db_running:
                log.warning(f"[RECONCILE] Job #{job_id}: In memory but DB says not running → killing orphan FFmpeg")
                _kill_orphan_process(job_id)

    except Exception as e:
        log.error(f"[RECONCILE] Error during reconciliation: {e}", exc_info=True)
    finally:
        conn.close()

    log.info("[RECONCILE] Reconciliation done")

    # ── Recovery: auto-resume jobs interrupted by container restart ──
    _recover_interrupted_jobs()


def _recover_interrupted_jobs():
    """
    After container restart, find jobs that were stopped due to 'Worker shutdown'
    and are still within their duration window. Auto-resume them.
    This handles the case where SIGTERM stopped the worker mid-stream.
    """
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Find jobs stopped by worker shutdown in the last 10 minutes
            # that are still within their duration window
            cur.execute("""
                SELECT id, channel_id, title, video_source, duration_hours,
                       started_at, finished_at, broadcast_id, quality,
                       use_mp3, use_sfx, error_message
                FROM live_jobs
                WHERE status = 'stopped'
                  AND error_message LIKE '%%Worker shutdown%%'
                  AND finished_at > NOW() - INTERVAL '10 minutes'
                  AND started_at IS NOT NULL
                  AND duration_hours IS NOT NULL
                ORDER BY id DESC
            """)
            recoverable = cur.fetchall()

        if not recoverable:
            return

        for job in recoverable:
            job_id = job["id"]
            started = job["started_at"]
            duration_h = job["duration_hours"]
            finished = job["finished_at"]

            if not started or not duration_h:
                continue

            # Calculate how much time is left
            from datetime import timedelta
            max_duration = timedelta(hours=duration_h)
            elapsed = finished - started if finished else timedelta(0)
            remaining = max_duration - elapsed

            if remaining.total_seconds() <= 0:
                log.info(f"[RECOVER] Job #{job_id}: Duration already exceeded ({elapsed} >= {max_duration}), skipping")
                continue

            # Check if channel is not already in use by another running job
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur2:
                cur2.execute("""
                    SELECT id FROM live_jobs
                    WHERE channel_id = %s AND status = 'running'
                """, (job["channel_id"],))
                existing = cur2.fetchone()

            if existing:
                log.info(f"[RECOVER] Job #{job_id}: Channel {job['channel_id']} already has running job #{existing['id']}, skipping")
                continue

            log.info(f"[RECOVER] Job #{job_id}: {remaining} remaining (of {max_duration}), resuming...")

            # Reset job status to pending so start_livestream can pick it up
            update_job(job_id,
                       status="pending",
                       error_message=None,
                       finished_at=None,
                       process_id=None,
                       stop_requested=False)

            # Reload job data for start_livestream
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur3:
                cur3.execute("SELECT * FROM live_jobs WHERE id = %s", (job_id,))
                refreshed_job = cur3.fetchone()

            if refreshed_job:
                try:
                    start_livestream(dict(refreshed_job))
                    log.info(f"[RECOVER] Job #{job_id}: Resume initiated successfully")
                except Exception as e:
                    log.error(f"[RECOVER] Job #{job_id}: Failed to resume: {e}")
                    update_job(job_id, status="failed",
                               error_message=f"Auto-resume failed: {str(e)}",
                               finished_at=datetime.now(timezone.utc).isoformat())

    except Exception as e:
        log.error(f"[RECOVER] Error during recovery: {e}", exc_info=True)
    finally:
        conn.close()


class _PIDSentinel:
    """Lightweight sentinel for a PID we're tracking but don't have a Popen object for."""
    def __init__(self, pid, job_id):
        self._pid = pid
        self._job_id = job_id

    @property
    def pid(self):
        return self._pid

    def poll(self):
        """Return None if alive, exit code if dead."""
        if _is_pid_alive(self._pid):
            return None
        return -1  # dead

    def terminate(self):
        try:
            os.kill(self._pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

    def kill(self):
        try:
            os.kill(self._pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    def wait(self, timeout=None):
        return 0


def _is_pid_alive(pid):
    """Check if a PID is alive."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _get_pid_cmdline(pid):
    """Read /proc/<pid>/cmdline to identify the process."""
    try:
        cmdline_path = f"/proc/{pid}/cmdline"
        if os.path.exists(cmdline_path):
            with open(cmdline_path, "rb") as f:
                return f.read().replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
    except Exception:
        pass
    return None


def _try_end_broadcast(db_job):
    """Try to end a YouTube broadcast for a job (best effort)."""
    broadcast_id = db_job.get("broadcast_id")
    channel_id = db_job.get("channel_id")
    if not broadcast_id or not channel_id:
        return
    try:
        channel = get_channel(channel_id)
        if channel:
            end_broadcast(broadcast_id, channel)
            log.info(f"[RECONCILE] Ended broadcast {broadcast_id} for job #{db_job['id']}")
    except Exception as e:
        log.warning(f"[RECONCILE] Failed to end broadcast {broadcast_id}: {e}")


def _kill_orphan_process(job_id):
    """Kill an orphan FFmpeg process and clean up."""
    proc = running_processes.get(job_id)
    if not proc:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception as e:
        log.warning(f"[RECONCILE] Error killing orphan for job #{job_id}: {e}")
    finally:
        running_processes.pop(job_id, None)
        stream_stats_store.pop(job_id, None)
        reconnect_counts.pop(job_id, None)


def startup_reconciliation():
    """
    Called once on worker start. Finds all DB 'running' jobs and reconciles.
    Also recovers jobs interrupted by container shutdown.
    """
    log.info("[STARTUP] Running startup reconciliation...")
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, channel_id, process_id, broadcast_id, video_source, status
                FROM live_jobs
                WHERE status = 'running'
                ORDER BY id ASC
            """)
            db_running = cur.fetchall()

        if db_running:
            log.info(f"[STARTUP] Found {len(db_running)} job(s) in 'running' state: {[r['id'] for r in db_running]}")

            for row in db_running:
                job_id = row["id"]
                pid = row["process_id"]

                if not pid:
                    log.warning(f"[STARTUP] Job #{job_id}: no process_id → marking failed")
                    update_job(job_id, status="failed", error_message="No process ID on startup",
                               finished_at=datetime.now(timezone.utc).isoformat())
                    continue

                alive = _is_pid_alive(pid)
                cmdline = _get_pid_cmdline(pid) if alive else None

                if alive and cmdline and "ffmpeg" in cmdline.lower():
                    log.info(f"[STARTUP] Job #{job_id}: FFmpeg PID {pid} is ALIVE → re-tracking")
                    running_processes[job_id] = _PIDSentinel(pid, job_id)
                else:
                    reason = f"PID {pid} dead" if not alive else f"PID {pid} reused by: {cmdline}"
                    log.warning(f"[STARTUP] Job #{job_id}: {reason} → marking failed")
                    _try_end_broadcast(row)
                    update_job(job_id, status="failed",
                               error_message=f"FFmpeg not running on startup ({reason})",
                               finished_at=datetime.now(timezone.utc).isoformat())
        else:
            log.info("[STARTUP] No jobs in 'running' state. Clean slate.")

    except Exception as e:
        log.error(f"[STARTUP] Reconciliation error: {e}", exc_info=True)
    finally:
        conn.close()

    log.info("[STARTUP] Startup reconciliation complete")

    # Auto-resume jobs interrupted by container shutdown
    _recover_interrupted_jobs()


# ── Real-time Monitoring ───────────────────────────────────────

def parse_ffmpeg_stats(line):
    """Parse FFmpeg stderr line for stream statistics."""
    stats = {}
    bitrate_match = re.search(r'bitrate=\s*([\d.]+)kbits/s', line)
    if bitrate_match:
        stats['bitrate'] = float(bitrate_match.group(1))
    fps_match = re.search(r'fps=\s*([\d.]+)', line)
    if fps_match:
        stats['fps'] = float(fps_match.group(1))
    frame_match = re.search(r'frame=\s*(\d+)', line)
    if frame_match:
        stats['frame'] = int(frame_match.group(1))
    speed_match = re.search(r'speed=\s*([\d.]+)x', line)
    if speed_match:
        stats['speed'] = float(speed_match.group(1))
    time_match = re.search(r'time=(\d{2}):(\d{2}):(\d{2})', line)
    if time_match:
        h, m, s = int(time_match.group(1)), int(time_match.group(2)), int(time_match.group(3))
        stats['elapsed_seconds'] = h * 3600 + m * 60 + s
    drop_match = re.search(r'(?:dup|drop)=\s*(\d+)', line)
    if drop_match:
        stats['drops'] = int(drop_match.group(1))
    return stats if stats else None


def monitor_ffmpeg_output(job_id, process):
    """Thread function to monitor FFmpeg stderr and update stats."""
    log.info(f"Job {job_id}: Monitor thread started")
    try:
        buffer = ""
        char_count = 0
        while process.poll() is None:
            char = process.stderr.read(1)
            if not char:
                break
            char = char.decode("utf-8", errors="replace")
            char_count += 1
            if char in ('\r', '\n'):
                if buffer.strip():
                    stats = parse_ffmpeg_stats(buffer)
                    if stats:
                        stream_stats_store[job_id] = stats
                        elapsed = stats.get('elapsed_seconds', 0)
                        if elapsed > 0 and elapsed % 10 == 0:
                            update_job_stats(job_id, stats)
                buffer = ""
            else:
                buffer += char
        log.info(f"Job {job_id}: Monitor thread ended, read {char_count} chars")
    except Exception as e:
        log.warning(f"Job {job_id}: Monitor thread error: {e}")


def update_job_stats(job_id, stats):
    """Update job with real-time stats."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE live_jobs
                SET stream_stats = %s,
                    current_bitrate = %s,
                    current_fps = %s,
                    frame_drop_count = %s,
                    last_health_check = NOW()
                WHERE id = %s
            """, (
                json.dumps(stats),
                int(stats.get('bitrate', 0)),
                stats.get('fps', 0.0),
                stats.get('drops', 0),
                job_id
            ))
            conn.commit()
    except Exception as e:
        log.warning(f"Job {job_id}: Failed to update stats: {e}")
    finally:
        conn.close()


def get_stream_stats(job_id):
    """Get current stream stats for a job."""
    return stream_stats_store.get(job_id, {})


def categorize_error(stderr, returncode):
    """Categorize FFmpeg error for better handling."""
    stderr_lower = stderr.lower()
    if returncode == 0:
        return None
    if any(kw in stderr_lower for kw in ['connection refused', 'network', 'timeout', 'rtmp']):
        return 'network'
    if any(kw in stderr_lower for kw in ['permission', 'access', 'denied', 'auth']):
        return 'auth'
    if any(kw in stderr_lower for kw in ['quota', 'limit', 'exceeded']):
        return 'quota'
    if any(kw in stderr_lower for kw in ['codec', 'encoder', 'decoder', 'format']):
        return 'ffmpeg'
    return 'unknown'


def get_channel(channel_id):
    """Get channel row from DB."""
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM channels WHERE id = %s", (channel_id,))
            return cur.fetchone()
    finally:
        conn.close()


def get_youtube_service(channel):
    """Build YouTube API service from channel OAuth tokens."""
    access_token = channel.get("access_token", "")
    refresh_token = channel.get("refresh_token", "")

    if not access_token and not refresh_token:
        return None

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/youtube.force-ssl"],
    )

    # Always try to refresh if token is expired or about to expire (within 5 minutes)
    # This prevents using a token that expires mid-API-call
    needs_refresh = False
    if creds.expired:
        needs_refresh = True
        log.info(f"Channel {channel['id']}: Token expired, refreshing...")
    elif creds.expiry:
        from datetime import timedelta
        time_left = creds.expiry - datetime.now(timezone.utc) if creds.expiry.tzinfo else creds.expiry - datetime.utcnow()
        if time_left < timedelta(minutes=5):
            needs_refresh = True
            log.info(f"Channel {channel['id']}: Token expiring in {time_left}, refreshing early...")

    if needs_refresh and creds.refresh_token:
        try:
            creds.refresh(Request())
            conn = get_db()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE channels SET access_token = %s, token_expires_at = %s WHERE id = %s",
                        (creds.token, creds.expiry, channel["id"]),
                    )
                    conn.commit()
            finally:
                conn.close()
            # Update token and set status to valid
            conn2 = get_db()
            try:
                with conn2.cursor() as cur2:
                    cur2.execute(
                        "UPDATE channels SET access_token = %s, token_expires_at = %s, token_status = 'valid', token_error = NULL, token_checked_at = NOW() WHERE id = %s",
                        (creds.token, creds.expiry, channel["id"]),
                    )
                    conn2.commit()
            finally:
                conn2.close()
            log.info(f"Channel {channel['id']}: OAuth token refreshed, new expiry: {creds.expiry}")
        except Exception as e:
            error_msg = str(e)
            log.error(f"Channel {channel['id']}: Token refresh failed: {error_msg}")
            # Set token_status to error
            conn3 = get_db()
            try:
                with conn3.cursor() as cur3:
                    cur3.execute(
                        "UPDATE channels SET token_status = 'error', token_error = %s, token_checked_at = NOW() WHERE id = %s",
                        (error_msg[:500], channel["id"]),
                    )
                    conn3.commit()
            finally:
                conn3.close()
            return None
    elif needs_refresh and not creds.refresh_token:
        log.error(f"Channel {channel['id']}: Token expired but no refresh token available")
        # Set token_status to expired
        conn4 = get_db()
        try:
            with conn4.cursor() as cur4:
                cur4.execute(
                    "UPDATE channels SET token_status = 'expired', token_error = 'No refresh token available', token_checked_at = NOW() WHERE id = %s",
                    (channel["id"],),
                )
                conn4.commit()
        finally:
            conn4.close()
        return None

    return build("youtube", "v3", credentials=creds)


def create_broadcast(channel, title, description, visibility="unlisted"):
    """
    Create YouTube live broadcast + stream, bind them.
    Returns (broadcast_id, stream_key) or (None, None) on error.
    """
    youtube = get_youtube_service(channel)
    if not youtube:
        log.error("Cannot create broadcast: no YouTube service")
        return None, None

    try:
        broadcast_body = {
            "snippet": {
                "title": title[:100] if title else "Live Stream",
                "description": (description or "")[:5000],
                "scheduledStartTime": datetime.now(timezone.utc).isoformat(),
            },
            "status": {
                "privacyStatus": visibility or "unlisted",
                "selfDeclaredMadeForKids": False,
            },
            "contentDetails": {
                "enableAutoStart": True,
                "enableAutoStop": False,
                "latencyPreference": "normal",
                "monitorStream": {"enableMonitorStream": False},
            },
        }

        broadcast_resp = youtube.liveBroadcasts().insert(
            part="snippet,status,contentDetails",
            body=broadcast_body,
        ).execute()

        broadcast_id = broadcast_resp["id"]
        log.info(f"Broadcast created: {broadcast_id}")

        stream_body = {
            "snippet": {
                "title": f"Stream for {title[:80]}" if title else "Livestream",
            },
            "cdn": {
                "frameRate": "30fps",
                "ingestionType": "rtmp",
                "resolution": "1080p",
            },
            "contentDetails": {
                "isReusable": False,
            },
        }

        stream_resp = youtube.liveStreams().insert(
            part="snippet,cdn,contentDetails",
            body=stream_body,
        ).execute()

        stream_key = stream_resp["cdn"]["ingestionInfo"]["streamName"]
        stream_id = stream_resp["id"]
        log.info(f"Stream created: {stream_id}, key: {stream_key[:8]}...")

        youtube.liveBroadcasts().bind(
            part="contentDetails",
            id=broadcast_id,
            streamId=stream_id,
        ).execute()
        log.info(f"Stream {stream_id} bound to broadcast {broadcast_id}")

        return broadcast_id, stream_key

    except Exception as e:
        log.error(f"Failed to create broadcast: {e}", exc_info=True)
        return None, None


def update_broadcast_metadata(broadcast_id, channel, title=None, description=None, tags=None):
    """Update metadata on an active broadcast without interrupting stream."""
    youtube = get_youtube_service(channel)
    if not youtube:
        return False

    try:
        current = youtube.liveBroadcasts().list(
            part="snippet",
            id=broadcast_id,
        ).execute()

        if not current.get("items"):
            log.error(f"Broadcast {broadcast_id} not found")
            return False

        snippet = current["items"][0]["snippet"]
        if title:
            snippet["title"] = title[:100]
        if description is not None:
            snippet["description"] = description[:5000]

        youtube.liveBroadcasts().update(
            part="snippet",
            body={"id": broadcast_id, "snippet": snippet},
        ).execute()

        log.info(f"Broadcast {broadcast_id} metadata updated")
        return True

    except Exception as e:
        log.error(f"Failed to update broadcast metadata: {e}")
        return False


def end_broadcast(broadcast_id, channel):
    """End a live broadcast (transition to complete)."""
    youtube = get_youtube_service(channel)
    if not youtube:
        return False

    try:
        youtube.liveBroadcasts().transition(
            broadcastStatus="complete",
            id=broadcast_id,
            part="status",
        ).execute()
        log.info(f"Broadcast {broadcast_id} ended")
        return True
    except Exception as e:
        log.error(f"Failed to end broadcast {broadcast_id}: {e}")
        return False


def upload_thumbnail_to_youtube(broadcast_id, channel, thumbnail_path):
    """Upload thumbnail to a YouTube broadcast."""
    if not thumbnail_path or not os.path.exists(thumbnail_path):
        log.info(f"Thumbnail not found or not specified: {thumbnail_path}")
        return False

    youtube = get_youtube_service(channel)
    if not youtube:
        log.error("Cannot upload thumbnail: no YouTube service")
        return False

    try:
        from googleapiclient.http import MediaFileUpload
        media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
        youtube.thumbnails().set(
            videoId=broadcast_id,
            media_body=media,
        ).execute()
        log.info(f"Thumbnail uploaded for broadcast {broadcast_id}: {thumbnail_path}")
        return True
    except Exception as e:
        log.warning(f"Thumbnail upload failed (non-fatal): {e}")
        return False


def poll_jobs():
    """Get jobs that need processing."""
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, channel_id, title, description, video_source,
                       stream_key, quality, duration_hours, use_mp3, use_sfx,
                       visibility, start_at_utc, end_at_utc
                FROM live_jobs
                WHERE status = 'pending'
                ORDER BY id ASC
                LIMIT 1
            """)
            pending = cur.fetchone()
            if pending:
                return dict(pending), "pending"

            now = datetime.now(timezone.utc)
            cur.execute("""
                SELECT id, channel_id, title, description, video_source,
                       stream_key, quality, duration_hours, use_mp3, use_sfx,
                       visibility, start_at_utc, end_at_utc
                FROM live_jobs
                WHERE status = 'scheduled'
                  AND start_at_utc <= %s
                ORDER BY start_at_utc ASC
                LIMIT 1
            """, (now,))
            scheduled = cur.fetchone()
            if scheduled:
                return dict(scheduled), "scheduled"

            return None, None
    finally:
        conn.close()


def update_job(job_id, **kwargs):
    """Update job fields."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            sets = ", ".join(f"{k} = %s" for k in kwargs)
            values = list(kwargs.values()) + [job_id]
            cur.execute(f"UPDATE live_jobs SET {sets} WHERE id = %s", values)
            conn.commit()
    finally:
        conn.close()


def get_channel_path(channel_id, asset_type):
    """Get storage path for a channel's asset type."""
    path = Path(STORAGE_PATH) / "assets" / asset_type / str(channel_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def find_video_source(channel_id, video_source):
    """Find video source file."""
    if video_source and os.path.exists(video_source):
        return video_source

    search_dirs = [
        get_channel_path(channel_id, "video-live"),
        get_channel_path(channel_id, "video-raw"),
        get_channel_path(channel_id, "video"),
    ]

    if video_source:
        for d in search_dirs:
            candidate = d / video_source
            if candidate.exists():
                return str(candidate)

    for d in search_dirs:
        if d.exists():
            for f in d.iterdir():
                if f.suffix.lower() in [".mp4", ".mkv", ".avi", ".mov"]:
                    return str(f)

    return None


def get_quality_settings(quality):
    """Get FFmpeg quality settings based on YouTube recommendations."""
    if quality == "high":
        return {
            "resolution": "1920x1080",
            "bitrate": "6800k",
            "maxrate": "6800k",
            "bufsize": "13600k",
        }
    else:
        return {
            "resolution": "1280x720",
            "bitrate": "4000k",
            "maxrate": "4000k",
            "bufsize": "8000k",
        }


def build_ffmpeg_command(job, video_path, stream_key):
    """Build FFmpeg command for livestreaming."""
    channel_id = job["channel_id"]
    quality = get_quality_settings(job["quality"])
    rtmp_url = f"rtmp://a.rtmp.youtube.com/live2/{stream_key}"

    cmd = ["ffmpeg", "-y", "-progress", "pipe:1"]
    cmd.extend(["-stream_loop", "-1", "-i", video_path])

    audio_filter = ""
    input_idx = 1

    if job["use_mp3"]:
        mp3_dir = get_channel_path(channel_id, "mp3")
        mp3_files = [str(f) for f in mp3_dir.iterdir() if f.suffix.lower() == ".mp3"]
        if mp3_files:
            concat_path = get_channel_path(channel_id, "tmp") / "live_concat.txt"
            with open(concat_path, "w") as f:
                for mp3 in mp3_files:
                    f.write(f"file '{mp3}'\n")
            cmd.extend(["-f", "concat", "-safe", "0", "-i", str(concat_path)])
            audio_filter = f"[{input_idx}:a]aloop=loop=-1:size=2e+09[mp3loop];"
            mp3_idx = input_idx
            input_idx += 1
        else:
            mp3_idx = None
    else:
        mp3_idx = None

    if job["use_sfx"]:
        sfx_dir = get_channel_path(channel_id, "sfx")
        sfx_files = [str(f) for f in sfx_dir.iterdir() if f.suffix.lower() in [".mp3", ".wav"]]
        if sfx_files:
            cmd.extend(["-i", sfx_files[0]])
            sfx_idx = input_idx
            input_idx += 1
        else:
            sfx_idx = None
    else:
        sfx_idx = None

    filter_parts = []
    w, h = quality["resolution"].split("x")
    filter_parts.append(f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2[vout]")

    if mp3_idx is not None and sfx_idx is not None:
        filter_parts.append(f"[mp3loop][{sfx_idx}:a]amix=inputs=2:duration=longest[aout]")
    elif mp3_idx is not None:
        filter_parts.append("[mp3loop]acopy[aout]")
    else:
        filter_parts.append("[0:a]acopy[aout]")

    filter_complex = audio_filter + ";".join(filter_parts)

    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-b:v", quality["bitrate"],
        "-maxrate", quality["maxrate"],
        "-bufsize", quality["bufsize"],
        "-g", "50",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        "-f", "flv",
        rtmp_url,
    ])

    return cmd


def _is_channel_in_use(channel_id):
    """
    Check if a channel already has a running FFmpeg.
    Checks BOTH in-memory running_processes AND live DB state.
    Returns (is_used, existing_job_id) tuple.
    """
    # Check in-memory first
    for jid, proc in running_processes.items():
        if proc.poll() is None:
            conn = get_db()
            try:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute("SELECT channel_id FROM live_jobs WHERE id = %s", (jid,))
                    row = cur.fetchone()
                    if row and row["channel_id"] == channel_id:
                        return True, jid
            finally:
                conn.close()

    # Also check DB directly (covers case where in-memory state is stale)
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id FROM live_jobs
                WHERE channel_id = %s AND status = 'running'
                ORDER BY id DESC LIMIT 1
            """, (channel_id,))
            row = cur.fetchone()
            if row:
                return True, row["id"]
    finally:
        conn.close()

    return False, None


def start_livestream(job):
    """Start a livestream: create YouTube broadcast, then start FFmpeg."""
    job_id = job["id"]
    channel_id = job["channel_id"]

    log.info(f"Starting livestream job #{job_id} for channel {channel_id}")

    # ── Guard: check if channel already has a running stream ──
    in_use, existing_job = _is_channel_in_use(channel_id)
    if in_use:
        log.warning(f"Job #{job_id}: Channel {channel_id} already in use by job #{existing_job} → rejecting")
        update_job(job_id, status="failed",
                   error_message=f"Channel {channel_id} already has running livestream (job #{existing_job})")
        return

    # Get channel for YouTube API
    channel = get_channel(channel_id)
    if not channel:
        update_job(job_id, status="failed", error_message="Channel not found in database")
        log.error(f"Job #{job_id}: Channel {channel_id} not found")
        return

    # Find video source
    video_path = find_video_source(channel_id, job["video_source"])
    if not video_path:
        update_job(job_id, status="failed", error_message="No video source found")
        log.error(f"Job #{job_id}: No video source found")
        return

    log.info(f"Job #{job_id}: Video source = {video_path}")

    # --- YouTube API: Create broadcast ---
    broadcast_id = None
    actual_stream_key = None  # the key actually used for FFmpeg

    if channel.get("access_token"):
        log.info(f"Job #{job_id}: Creating YouTube broadcast...")
        broadcast_id, yt_stream_key = create_broadcast(
            channel,
            title=job.get("title"),
            description=job.get("description"),
            visibility=job.get("visibility", "unlisted"),
        )

        if broadcast_id and yt_stream_key:
            actual_stream_key = yt_stream_key
            # Store both broadcast_id AND the actual stream_key for audit
            update_job(job_id, broadcast_id=broadcast_id, stream_key=yt_stream_key)
            log.info(f"Job #{job_id}: Broadcast {broadcast_id} created, stream_key={yt_stream_key[:8]}...")

            thumbnail_path = job.get("thumbnail_path")
            if thumbnail_path:
                upload_thumbnail_to_youtube(broadcast_id, channel, thumbnail_path)
        else:
            log.warning(f"Job #{job_id}: Broadcast creation failed, falling back to channel stream key")
    else:
        log.warning(f"Job #{job_id}: No OAuth token, using channel stream key directly")

    # Fallback to channel's default stream key
    if not actual_stream_key:
        actual_stream_key = channel.get("stream_key") or job.get("stream_key")

    if not actual_stream_key:
        update_job(job_id, status="failed", error_message="No stream key available")
        log.error(f"Job #{job_id}: No stream key")
        return

    # ── SAFETY LOG: confirm which channel + stream key we're about to use ──
    log.info(f"Job #{job_id}: SAFETY CHECK → channel_id={channel_id}, video={video_path}, "
             f"stream_key={actual_stream_key[:8]}..., broadcast={broadcast_id}")

    # Build FFmpeg command
    cmd = build_ffmpeg_command(job, video_path, actual_stream_key)
    log.info(f"Job #{job_id}: FFmpeg command = {' '.join(cmd[:10])}...")

    # Start FFmpeg process
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        running_processes[job_id] = process
        reconnect_counts[job_id] = 0

        # Start monitoring thread
        log.info(f"Job #{job_id}: Starting monitor thread...")
        monitor_thread = threading.Thread(target=monitor_ffmpeg_output, args=(job_id, process), daemon=True)
        monitor_thread.start()
        log.info(f"Job #{job_id}: Monitor thread started, alive={monitor_thread.is_alive()}")

        now = datetime.now(timezone.utc)
        update_job(
            job_id,
            status="running",
            process_id=process.pid,
            started_at=now.isoformat(),
        )

        log.info(f"Job #{job_id}: FFmpeg started with PID {process.pid}")

    except Exception as e:
        update_job(job_id, status="failed", error_message=str(e))
        log.error(f"Job #{job_id}: Failed to start FFmpeg: {e}")


def _attempt_reconnect(job_id):
    """Attempt to reconnect FFmpeg for a job that failed."""
    current_count = reconnect_counts.get(job_id, 0)
    if current_count >= MAX_RECONNECTS:
        log.error(f"Job #{job_id}: Max reconnect attempts ({MAX_RECONNECTS}) reached, giving up")
        return False

    log.info(f"Job #{job_id}: Attempting reconnect {current_count + 1}/{MAX_RECONNECTS}...")
    reconnect_counts[job_id] = current_count + 1
    update_job(job_id, reconnect_attempts=current_count + 1)

    # Get job details from DB
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM live_jobs WHERE id = %s", (job_id,))
            job = cur.fetchone()
    finally:
        conn.close()

    if not job:
        log.error(f"Job #{job_id}: Job not found in DB, cannot reconnect")
        return False

    if job["status"] != "running":
        log.warning(f"Job #{job_id}: Status is '{job['status']}', not 'running', skipping reconnect")
        return False

    channel_id = job["channel_id"]
    channel = get_channel(channel_id)
    if not channel:
        log.error(f"Job #{job_id}: Channel {channel_id} not found, cannot reconnect")
        return False

    # Get video source
    video_path = find_video_source(channel_id, job["video_source"])
    if not video_path:
        log.error(f"Job #{job_id}: Video source not found, cannot reconnect")
        return False

    # Get stream key (use existing broadcast if available)
    stream_key = job["stream_key"]
    if not stream_key:
        stream_key = channel.get("stream_key", "")

    if not stream_key:
        log.error(f"Job #{job_id}: No stream key available, cannot reconnect")
        return False

    # Wait before reconnecting
    log.info(f"Job #{job_id}: Waiting {RECONNECT_DELAY}s before reconnect...")
    time.sleep(RECONNECT_DELAY)

    # Build and start FFmpeg
    try:
        cmd = build_ffmpeg_command(dict(job), video_path, stream_key)
        log.info(f"Job #{job_id}: Reconnect FFmpeg command = {' '.join(cmd[:10])}...")

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        running_processes[job_id] = process

        # Start new monitor thread
        monitor_thread = threading.Thread(target=monitor_ffmpeg_output, args=(job_id, process), daemon=True)
        monitor_thread.start()

        # Update DB with new PID
        update_job(job_id, process_id=process.pid, last_health_check=datetime.now(timezone.utc).isoformat())

        log.info(f"Job #{job_id}: Reconnect successful! New PID: {process.pid}")
        return True

    except Exception as e:
        log.error(f"Job #{job_id}: Reconnect failed: {e}")
        return False


def check_running_jobs():
    """Check health of running jobs, with auto-reconnect on failure."""
    for job_id, proc in list(running_processes.items()):
        if proc.poll() is not None:
            # Process has exited
            returncode = proc.returncode if hasattr(proc, 'returncode') else -1

            # Try to read stderr (only available for real Popen, not PIDSentinel)
            stderr = ""
            if hasattr(proc, 'stderr') and proc.stderr:
                try:
                    stderr = proc.stderr.read().decode("utf-8", errors="replace")[-500:]
                except Exception:
                    pass

            if returncode == 0:
                # Normal exit (duration exceeded or manual stop)
                update_job(job_id, status="finished", finished_at=datetime.now(timezone.utc).isoformat())
                log.info(f"Job #{job_id}: Finished normally")
                # Cleanup
                del running_processes[job_id]
                stream_stats_store.pop(job_id, None)
                reconnect_counts.pop(job_id, None)
            else:
                # FFmpeg crashed — attempt reconnect
                err_msg = f"FFmpeg exit code {returncode}: {stderr}" if stderr else f"FFmpeg exit code {returncode}"
                log.warning(f"Job #{job_id}: FFmpeg crashed — {err_msg}")

                # Remove dead process from tracking
                del running_processes[job_id]
                stream_stats_store.pop(job_id, None)

                # Attempt reconnect
                reconnected = _attempt_reconnect(job_id)
                if not reconnected:
                    # Reconnect failed, mark as failed
                    update_job(job_id, status="failed", error_message=f"FFmpeg crashed and reconnect failed: {err_msg}",
                               finished_at=datetime.now(timezone.utc).isoformat())
                    reconnect_counts.pop(job_id, None)
                    log.error(f"Job #{job_id}: Marked as failed after reconnect failure")

        else:
            # Process still alive — check duration
            conn = get_db()
            try:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute("SELECT duration_hours, started_at FROM live_jobs WHERE id = %s", (job_id,))
                    row = cur.fetchone()
                    if row and row["started_at"] and row["duration_hours"]:
                        elapsed = (datetime.now(timezone.utc) - row["started_at"]).total_seconds()
                        max_duration = row["duration_hours"] * 3600
                        if elapsed > max_duration:
                            log.info(f"Job #{job_id}: Duration exceeded ({elapsed:.0f}s > {max_duration}s), stopping")
                            stop_livestream(job_id)
            finally:
                conn.close()


def stop_livestream(job_id):
    """Stop a running livestream and end the YouTube broadcast."""
    proc = running_processes.get(job_id)
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    # End YouTube broadcast
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT channel_id, broadcast_id FROM live_jobs WHERE id = %s", (job_id,))
            row = cur.fetchone()
            if row and row.get("broadcast_id"):
                channel = get_channel(row["channel_id"])
                if channel:
                    end_broadcast(row["broadcast_id"], channel)
    finally:
        conn.close()

    update_job(job_id, status="stopped", stop_requested=False, finished_at=datetime.now(timezone.utc).isoformat())
    running_processes.pop(job_id, None)
    stream_stats_store.pop(job_id, None)
    reconnect_counts.pop(job_id, None)
    log.info(f"Job #{job_id}: Stopped and cleaned up")


def check_stopped_jobs():
    """Check for jobs that should be stopped based on end_at_utc."""
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id FROM live_jobs
                WHERE status = 'running'
                  AND end_at_utc IS NOT NULL
                  AND end_at_utc <= %s
            """, (datetime.now(timezone.utc),))
            for row in cur.fetchall():
                log.info(f"Job #{row['id']}: end_at_utc reached, stopping")
                stop_livestream(row["id"])
    finally:
        conn.close()


def graceful_shutdown(sig, frame):
    """
    Handle SIGTERM/SIGINT gracefully.
    Kill all FFmpeg processes and update DB status before exiting.
    Docker sends SIGTERM, waits 10s, then SIGKILL.
    We must finish within 10 seconds.
    """
    global _shutdown_requested
    sig_name = signal.Signals(sig).name if hasattr(signal, 'Signals') else str(sig)
    log.warning(f"[SHUTDOWN] Received {sig_name} — initiating graceful shutdown...")
    _shutdown_requested = True

    # Immediately kill all running FFmpeg processes
    for job_id, proc in list(running_processes.items()):
        try:
            if proc.poll() is None:
                log.info(f"[SHUTDOWN] Terminating FFmpeg for job #{job_id} (PID {proc.pid})")
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    log.warning(f"[SHUTDOWN] Force-killing FFmpeg for job #{job_id}")
                    proc.kill()
                    proc.wait(timeout=2)

            # Update DB: mark as stopped (not failed — this is an intentional shutdown)
            update_job(job_id,
                       status="stopped",
                       error_message=f"Worker shutdown ({sig_name})",
                       finished_at=datetime.now(timezone.utc).isoformat())
            log.info(f"[SHUTDOWN] Job #{job_id} marked as stopped")
        except Exception as e:
            log.error(f"[SHUTDOWN] Error cleaning up job #{job_id}: {e}")

    # Cleanup
    running_processes.clear()
    stream_stats_store.clear()
    reconnect_counts.clear()

    log.info("[SHUTDOWN] All FFmpeg processes terminated. Exiting.")
    sys.exit(0)


def main():
    """Main worker loop."""
    global _shutdown_requested

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT, graceful_shutdown)
    log.info("[MAIN] Signal handlers registered (SIGTERM, SIGINT)")

    log.info("=" * 60)
    log.info("Livestream worker started (FIXED v4 - with health server + stop commands)")
    log.info(f"Database: {DB_URL.split('@')[1]}")
    log.info(f"Storage: {STORAGE_PATH}")
    log.info(f"Poll interval: {POLL_INTERVAL}s")
    log.info(f"Google Client ID: {GOOGLE_CLIENT_ID[:20]}..." if GOOGLE_CLIENT_ID else "WARNING: No GOOGLE_CLIENT_ID")
    log.info("=" * 60)

    # ── Startup reconciliation: recover from previous crash/restart ──
    startup_reconciliation()

    # ── Start health HTTP server ──
    start_health_server()

    global _reconcile_counter

    while not _shutdown_requested:
        try:
            # Check for new jobs
            job, job_type = poll_jobs()
            if job:
                start_livestream(job)

            # Check running jobs health
            check_running_jobs()

            # Check for jobs that should be stopped
            check_stopped_jobs()

            # Check for user-initiated stop commands via DB
            check_stop_requests()

            # Periodic reconciliation
            _reconcile_counter += 1
            if _reconcile_counter >= RECONCILE_EVERY:
                _reconcile_counter = 0
                reconcile_running_jobs()

            time.sleep(POLL_INTERVAL)

        except psycopg2.OperationalError as e:
            log.error(f"Database connection error: {e}")
            time.sleep(10)
        except Exception as e:
            log.error(f"Unexpected error: {e}", exc_info=True)
            time.sleep(5)

    # If we get here, shutdown was requested
    log.info("[MAIN] Shutdown flag set, exiting main loop")


if __name__ == "__main__":
    main()
