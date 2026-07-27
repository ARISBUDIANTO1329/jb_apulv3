#!/usr/bin/env python3
"""
Production Worker / Orchestrator - JB APUL v3
Polls database for pending production jobs and processes them.

3 Modes:
  1. ready_video (Final Production) → audio_engine → video_loop_engine → final_renderer
  2. raw_video_auto_seamless → master_preprocess.py (seamless loop)
  3. merge_video (Dynamic) → merge_video_worker.py (random concat)
"""

import json
import os
import subprocess
import sys
import time
import logging
from pathlib import Path

import psycopg2
import psycopg2.extras
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import append_log

# Config
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://jb_user:change-me@db:5432/jb_apulv3")
STORAGE_PATH = os.environ.get("STORAGE_PATH", "/app/storage")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "5"))

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [PRODUCTION] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("production")

DB_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
PYTHON = sys.executable
BASE_DIR = Path(__file__).resolve().parent
ENGINE_DIR = BASE_DIR / "engine"
UTILS_DIR = BASE_DIR / "utils"


def get_db():
    return psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def log_to_file(message: str):
    """Append to production log file."""
    log_path = Path(STORAGE_PATH) / "logs" / "production_worker.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(str(message) + "\n")


def run_step(step_name: str, cmd: list, job_id: int = 0) -> bool:
    """Run a subprocess step, log output."""
    log.info(f"[ORCH] START {step_name}")
    log_to_file(f"[ORCH] START {step_name}")
    append_log(job_id, f"[ORCH] START {step_name}")

    process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    output = (process.stdout or "").strip()

    if output:
        for line in output.splitlines():
            log.info(line)
            log_to_file(line)

    if process.returncode != 0:
        log.error(f"[ORCH] FAIL {step_name}")
        log_to_file(f"[ORCH] FAIL {step_name}")
        append_log(job_id, f"[ORCH] FAIL {step_name}")
        return False

    log.info(f"[ORCH] DONE {step_name}")
    log_to_file(f"[ORCH] DONE {step_name}\n")
    append_log(job_id, f"[ORCH] DONE {step_name}")
    return True


def cleanup_job_tmp(job_id: int):
    """Remove temp files for a job on failure."""
    tmp_dir = os.path.join(STORAGE_PATH, "tmp")
    if not os.path.isdir(tmp_dir):
        return
    job_id_str = str(job_id)
    removed = 0
    try:
        for filename in os.listdir(tmp_dir):
            tmp_path = os.path.join(tmp_dir, filename)
            if not os.path.isfile(tmp_path):
                continue
            should_delete = False
            if f"_{job_id_str}.mp4" in filename or f"_{job_id_str}.wav" in filename:
                should_delete = True
            elif filename.startswith(f"_mp3_merge_{job_id_str}"):
                should_delete = True
            if should_delete:
                os.remove(tmp_path)
                removed += 1
        if removed > 0:
            log.info(f"[CLEANUP] Removed {removed} temp files for job {job_id}")
    except Exception as e:
        log.warning(f"[CLEANUP] Warning: {e}")


def poll_jobs():
    """Get next pending production job."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id FROM production_jobs
                WHERE status = 'pending'
                ORDER BY id ASC LIMIT 1
            """)
            return cur.fetchone()
    finally:
        conn.close()


def update_job(job_id: int, **kwargs):
    """Update job fields."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            sets = ", ".join(f"{k} = %s" for k in kwargs)
            values = list(kwargs.values()) + [job_id]
            cur.execute(f"UPDATE production_jobs SET {sets}, updated_at=NOW() WHERE id = %s", values)
            conn.commit()
    finally:
        conn.close()


def get_job(job_id: int) -> dict:
    """Get full job record."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM production_jobs WHERE id=%s", (job_id,))
            return cur.fetchone()
    finally:
        conn.close()


def process_final_production(job_id: int):
    """
    Mode 1: Final Production (ready_video)
    Pipeline: audio_engine → video_loop_engine → final_renderer
    """
    log.info(f"[FINAL] Processing job {job_id}")
    log_to_file(f"[FINAL] Processing job {job_id}")
    append_log(job_id, f"[FINAL] Processing job {job_id}")

    env = {**os.environ, "STORAGE_PATH": STORAGE_PATH}

    # Step 1: Audio
    if not run_step("audio_engine", [PYTHON, str(ENGINE_DIR / "audio_engine.py"), str(job_id), STORAGE_PATH], job_id):
        cleanup_job_tmp(job_id)
        update_job(job_id, status="failed", error_message="Audio engine failed", final_status="failed")
        return

    # Step 2: Video Loop
    if not run_step("video_loop_engine", [PYTHON, str(ENGINE_DIR / "video_loop_engine.py"), str(job_id), STORAGE_PATH], job_id):
        cleanup_job_tmp(job_id)
        update_job(job_id, status="failed", error_message="Video loop engine failed", final_status="failed")
        return

    # Step 3: Final Render
    if not run_step("final_renderer", [PYTHON, str(ENGINE_DIR / "final_renderer.py"), str(job_id), STORAGE_PATH], job_id):
        cleanup_job_tmp(job_id)
        # Note: final_renderer.py already sets specific error message in DB
        # Only set generic message if the engine didn't set one
        job = get_job(job_id)
        if job and not job.get("error_message"):
            update_job(job_id, status="failed", error_message="Final renderer failed", final_status="failed")
        return

    log.info(f"[FINAL] Job {job_id} COMPLETED")
    log_to_file(f"[FINAL] Job {job_id} COMPLETED\n")
    append_log(job_id, f"[FINAL] Job {job_id} COMPLETED")


def process_auto_seamless(job_id: int):
    """
    Mode 2: Auto Seamless (raw_video_auto_seamless)
    Preprocess raw video into seamless loop.
    """
    log.info(f"[SEAMLESS] Processing job {job_id}")
    job = get_job(job_id)
    if not job:
        return

    channel_id = job["channel_id"]
    video_source = job["video_source"]
    assets = os.path.join(STORAGE_PATH, "assets")

    raw_path = os.path.join(assets, "video-raw", str(channel_id), video_source)
    if not os.path.exists(raw_path):
        update_job(job_id, status="failed", error_message=f"Raw video not found: {video_source}", final_status="failed")
        return

    output_name = f"final_raw_{Path(video_source).stem}_{int(time.time())}.mp4"
    output_path = os.path.join(assets, "video", str(channel_id), output_name)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    tail_length = str(job.get("tail_length") or 3)
    cmd = [PYTHON, str(UTILS_DIR / "master_preprocess.py"), raw_path, output_path, tail_length]

    if not run_step("auto_seamless", cmd, job_id):
        update_job(job_id, status="failed", error_message="Seamless preprocess failed", final_status="failed")
        return

    # Slowmo post-processing
    slowmo_percent = int(job.get("slowmo_percent") or 0)
    if slowmo_percent > 0:
        speed_factor = 1 - (slowmo_percent / 100)
        if speed_factor <= 0:
            speed_factor = 1.0
        pts_multiplier = f"{1 / speed_factor:.3f}"
        slowmo_tmp = output_path.replace(".mp4", "_slowmo_tmp.mp4")

        slowmo_cmd = [
            "ffmpeg", "-y", "-i", output_path,
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-filter:v", f"setpts={pts_multiplier}*PTS",
            "-map", "0:v:0", "-map", "1:a:0", "-shortest",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", slowmo_tmp,
        ]

        if not run_step("slowmo_postprocess", slowmo_cmd, job_id):
            update_job(job_id, status="failed", error_message="Slowmo post-process failed", final_status="failed")
            if os.path.exists(slowmo_tmp):
                os.remove(slowmo_tmp)
            return

        os.remove(output_path)
        os.rename(slowmo_tmp, output_path)

    # Create media_items record
    conn = get_db()
    try:
        with conn.cursor() as cur:
            size_bytes = int(os.path.getsize(output_path)) if os.path.exists(output_path) else 0
            relative_path = f"assets/video/{channel_id}/{output_name}"
            cur.execute("""
                INSERT INTO media_items (channel_id, filename, file_path, asset_type, file_size, created_at)
                VALUES (%s, %s, %s, 'video', %s, NOW())
            """, (channel_id, output_name, relative_path, size_bytes))
            conn.commit()
    finally:
        conn.close()

    update_job(job_id, status="done", progress=100, final_status="done", final_path=output_path,
               output_filename=output_name, process_status="Seamless done")
    log.info(f"[SEAMLESS] Job {job_id} COMPLETED: {output_name}")


def process_dynamic_video(job_id: int):
    """
    Mode 3: Dynamic Video (merge_video)
    Random merge of raw videos with transitions.
    """
    log.info(f"[DYNAMIC] Processing job {job_id}")
    job = get_job(job_id)
    if not job:
        return

    channel_id = job["channel_id"]
    assets = os.path.join(STORAGE_PATH, "assets")
    raw_folder = os.path.join(assets, "video-raw", str(channel_id))

    if not os.path.isdir(raw_folder):
        update_job(job_id, status="failed", error_message="Video Raw folder not found", final_status="failed")
        return

    # Dynamic merge config from job or defaults
    merge_count = int(job.get("merge_count") or 10)
    merge_resolution = str(job.get("merge_resolution") or "1920x1080")
    merge_transition_enabled = "1" if job.get("merge_transition_enabled", True) else "0"
    merge_transition_name = str(job.get("merge_transition_name") or "fade")
    merge_transition_duration = str(job.get("merge_transition_duration") or "1.0")
    merge_speed = str(job.get("merge_speed") or "1.0")
    output_name = f"dynamic_merge_{int(time.time())}_{job_id}.mp4"
    output_path = os.path.join(assets, "video", str(channel_id), output_name)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    temp_dir = os.path.join(STORAGE_PATH, "tmp", f"merge_job_{job_id}")

    cmd = [
        PYTHON, str(BASE_DIR / "merge_video_worker.py"),
        "--channel-id", str(channel_id),
        "--job-id", str(job_id),
        "--input-folder", raw_folder,
        "--output-file", output_path,
        "--temp-dir", temp_dir,
        "--count", str(merge_count),
        "--resolution", merge_resolution,
        "--transition-enabled", merge_transition_enabled,
        "--transition-name", merge_transition_name,
        "--transition-duration", merge_transition_duration,
        "--speed", merge_speed,
        "--slow-enabled", ("1" if float(merge_speed) != 1.0 else "0"),
    ]

    if not run_step("dynamic_merge", cmd, job_id):
        update_job(job_id, status="failed", error_message="Dynamic merge failed", final_status="failed")
        return

    # Parse output
    try:
        # The merge worker outputs JSON, get from stdout
        size_bytes = int(os.path.getsize(output_path)) if os.path.exists(output_path) else 0
        relative_path = f"assets/video/{channel_id}/{output_name}"

        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO media_items (channel_id, filename, file_path, asset_type, file_size, created_at)
                    VALUES (%s, %s, %s, 'video', %s, NOW())
                """, (channel_id, output_name, relative_path, size_bytes))
                conn.commit()
        finally:
            conn.close()

        update_job(job_id, status="done", progress=100, final_status="done", final_path=output_path,
                   output_filename=output_name, process_status="Dynamic merge done")
        log.info(f"[DYNAMIC] Job {job_id} COMPLETED: {output_name}")

    except Exception as exc:
        update_job(job_id, status="failed", error_message=str(exc), final_status="failed")
        log.error(f"[DYNAMIC] Job {job_id} FAILED: {exc}")


def main():
    log.info("=" * 50)
    log.info("Production Worker v3 STARTED")
    log.info(f"Storage: {STORAGE_PATH}")
    log.info(f"Poll interval: {POLL_INTERVAL}s")
    log.info(f"Engine dir: {ENGINE_DIR}")
    log.info("=" * 50)

    while True:
        try:
            row = poll_jobs()
            if not row:
                time.sleep(POLL_INTERVAL)
                continue

            job_id = row["id"]
            job = get_job(job_id)
            if not job:
                time.sleep(POLL_INTERVAL)
                continue

            mode = job.get("production_mode", "v2")
            method = job.get("production_method", "ready_video")

            log.info(f"[ORCH] Job {job_id}: mode={mode}, method={method}")

            if method == "raw_video_auto_seamless":
                process_auto_seamless(job_id)
            elif method == "merge_video":
                process_dynamic_video(job_id)
            else:
                # Default: Final Production (ready_video / v2)
                process_final_production(job_id)

            time.sleep(1)

        except psycopg2.OperationalError as e:
            log.error(f"Database connection error: {e}")
            time.sleep(10)
        except Exception as e:
            log.error(f"Unexpected error: {e}", exc_info=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
