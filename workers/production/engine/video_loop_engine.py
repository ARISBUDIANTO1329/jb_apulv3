#!/usr/bin/env python3
"""
VIDEO LOOP ENGINE - JB APUL v3
Loops/trims video to match audio duration, with optional intro.
Ported from v2 with v3 path conventions.
"""

import os
import sys
import subprocess
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import get_db, update_progress, append_log

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


def get_duration(path: str) -> float:
    """Get media duration in seconds."""
    r = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        return float(r.stdout.strip())
    except (ValueError, AttributeError):
        return 0.0


def run_ffmpeg(cmd: list):
    """Run FFmpeg command, exit on failure."""
    p = subprocess.run(cmd)
    if p.returncode != 0:
        sys.exit(1)


def main():
    if len(sys.argv) != 3:
        print("[VIDEO] Usage: video_loop_engine.py <job_id> <storage_path>")
        sys.exit(1)

    job_id = int(sys.argv[1])
    storage_path = sys.argv[2]
    assets = os.path.join(storage_path, "assets")
    tmp_dir = os.path.join(storage_path, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    # Load job
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM production_jobs WHERE id=%s", (job_id,))
    job = cur.fetchone()

    if not job:
        append_log(job_id, f"Job {job_id} not found")
        print(f"[VIDEO] Job {job_id} not found")
        sys.exit(1)

    update_progress(job_id, 5, "Video: memuat job")
    append_log(job_id, "Video: memuat job")
    print(f"[VIDEO] Video: memuat job")

    if job["video_status"] == "done":
        append_log(job_id, f"Job {job_id} already done, skip")
        print(f"[VIDEO] Job {job_id} already done, skip")
        sys.exit(0)

    if job["audio_status"] != "done":
        append_log(job_id, f"Audio not done for job {job_id}")
        print(f"[VIDEO] Audio not done for job {job_id}")
        sys.exit(1)

    audio_path = job["audio_path"]
    if not audio_path or not os.path.exists(audio_path):
        append_log(job_id, f"Invalid audio_path: {audio_path}")
        print(f"[VIDEO] Invalid audio_path: {audio_path}")
        sys.exit(1)

    audio_duration = get_duration(audio_path)
    channel_id = job["channel_id"]
    video_source = job["video_source"]

    append_log(job_id, f"Audio duration: {audio_duration:.0f}s | Source: {video_source}")

    print(f"[VIDEO] Audio duration: {audio_duration:.0f}s | Source: {video_source}")
    update_progress(job_id, 10, "Video: menyiapkan source")
    append_log(job_id, "Video: menyiapkan source")
    print(f"[VIDEO] Video: menyiapkan source")

    if not video_source:
        print("[VIDEO] video_source empty")
        sys.exit(1)

    main_video = os.path.join(assets, "video", str(channel_id), video_source)
    if not os.path.exists(main_video):
        append_log(job_id, f"Main video not found: {main_video}")
        print(f"[VIDEO] Main video not found: {main_video}")
        sys.exit(1)

    main_video_duration = get_duration(main_video)

    # Intro handling
    intro_video = None
    intro_duration = 0
    if job.get("intro_file"):
        intro_video = os.path.join(assets, "intro", str(channel_id), job["intro_file"])
        if not os.path.exists(intro_video):
            append_log(job_id, f"Intro not found: {intro_video}")
            print(f"[VIDEO] Intro not found: {intro_video}")
            sys.exit(1)
        intro_duration = get_duration(intro_video)

    main_target_duration = audio_duration - intro_duration if intro_video else audio_duration
    if main_target_duration <= 0:
        print("[VIDEO] Invalid target duration")
        sys.exit(1)

    update_progress(job_id, 20, "Video: membuat segmen")
    append_log(job_id, "Video: membuat segmen")
    print(f"[VIDEO] Video: membuat segmen")
    segments = []

    # Intro segment
    if intro_video:
        seg_intro = os.path.join(tmp_dir, f"seg_intro_{job_id}.mp4")
        run_ffmpeg([FFMPEG, "-y", "-i", intro_video, "-t", str(intro_duration), "-c", "copy", seg_intro])
        segments.append(seg_intro)

    # Main video segment (skip intro portion)
    seg_continue = os.path.join(tmp_dir, f"seg_continue_{job_id}.mp4")
    continue_duration = min(max(0, main_video_duration - intro_duration), main_target_duration)
    run_ffmpeg([
        FFMPEG, "-y",
        "-ss", str(intro_duration), "-i", main_video,
        "-t", str(continue_duration), "-c", "copy", seg_continue,
    ])
    segments.append(seg_continue)

    # Loop remaining
    remaining = main_target_duration - continue_duration
    if remaining > 0:
        seg_loop = os.path.join(tmp_dir, f"seg_loop_{job_id}.mp4")
        run_ffmpeg([
            FFMPEG, "-y",
            "-stream_loop", "-1", "-i", main_video,
            "-t", str(remaining), "-c", "copy", seg_loop,
        ])
        segments.append(seg_loop)

    # Concat all segments
    append_log(job_id, f"Segments: {len(segments)} | Target: {main_target_duration:.0f}s")
    print(f"[VIDEO] Segments: {len(segments)} | Target: {main_target_duration:.0f}s")
    update_progress(job_id, 60, "Video: menggabung segmen")
    append_log(job_id, "Video: menggabung segmen")
    print(f"[VIDEO] Video: menggabung segmen")
    list_file = tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".txt")
    for seg in segments:
        list_file.write(f"file '{seg}'\n")
    list_file.close()

    update_progress(job_id, 80, "Video: finalisasi")
    append_log(job_id, "Video: finalisasi")
    print(f"[VIDEO] Video: finalisasi")
    output_video = os.path.join(tmp_dir, f"video_{job_id}.mp4")
    run_ffmpeg([
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_file.name,
        "-c", "copy", output_video,
    ])

    cur.execute(
        "UPDATE production_jobs SET video_status='done', video_path=%s, updated_at=NOW() WHERE id=%s",
        (output_video, job_id),
    )
    conn.commit()
    conn.close()

    size_mb = os.path.getsize(output_video) / (1024*1024)
    append_log(job_id, f"Output: {os.path.basename(output_video)} ({size_mb:.1f}MB)")
    print(f"[VIDEO] Output: {os.path.basename(output_video)} ({size_mb:.1f}MB)")
    append_log(job_id, f"Job {job_id} DONE")
    print(f"[VIDEO] Job {job_id} DONE")
    sys.exit(0)


if __name__ == "__main__":
    main()
