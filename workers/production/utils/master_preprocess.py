#!/usr/bin/env python3
"""
AUTO SEAMLESS PREPROCESS - JB APUL v3
Creates seamless loop from raw video with fade-to-transparent tail overlay.
Ported from v2 master_prod_v2_preprocess.py.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import get_db

DEFAULT_TAIL_LEN = 3.0
PROGRESS_ID = None


def update_progress(progress, status=None, message=None):
    """Update progress in auto_seamless_progresses table."""
    if not PROGRESS_ID:
        return
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """UPDATE auto_seamless_progresses
               SET progress=%s, status=COALESCE(%s, status),
                   message=COALESCE(%s, message), updated_at=NOW()
               WHERE id=%s""",
            (int(progress), status, message, int(PROGRESS_ID)),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def fail(message, code=1):
    update_progress(0, "failed", message)
    print(json.dumps({"ok": False, "message": message}, ensure_ascii=False))
    sys.exit(code)


def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)


def get_duration(input_file: str) -> float:
    result = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", input_file])
    if result.returncode != 0:
        fail("Failed to read video duration.\n" + (result.stdout or "").strip())
    try:
        return float((result.stdout or "").strip())
    except Exception:
        fail("Invalid duration from ffprobe.")


def main():
    global PROGRESS_ID

    if len(sys.argv) not in (3, 4, 5):
        fail("Usage: master_preprocess.py <input_file> <output_file> [tail_length] [progress_id]")

    input_path = Path(sys.argv[1]).resolve()
    output_path = Path(sys.argv[2]).resolve()

    # Parse tail length
    tail_len = DEFAULT_TAIL_LEN
    if len(sys.argv) >= 4:
        try:
            tail_len = float(sys.argv[3])
            if tail_len not in (1.0, 2.0, 3.0, 4.0, 5.0):
                fail("tail_length must be 1, 2, 3, 4, or 5.")
        except Exception:
            fail("Invalid tail_length.")

    # Parse progress ID
    if len(sys.argv) >= 5:
        try:
            PROGRESS_ID = int(sys.argv[4])
        except Exception:
            PROGRESS_ID = None

    update_progress(5, "processing", "Starting...")

    fade_start = round(tail_len * 0.10, 3)
    fade_end = round(tail_len * 0.90, 3)
    fade_duration = round(fade_end - fade_start, 3)

    if not input_path.is_file():
        fail("Input file not found.")
    if fade_duration <= 0:
        fail("Invalid fade timing.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    duration = get_duration(str(input_path))
    update_progress(10, "processing", "Duration read.")

    if duration <= tail_len:
        fail(f"Video duration must be > {int(tail_len)}s for seamless preprocess.")

    split_point = duration - tail_len
    temp_dir = Path(tempfile.mkdtemp(prefix="seamless_v3_"))

    body_path = temp_dir / "body.mp4"
    tail_path = temp_dir / "tail.mp4"
    tail_alpha_path = temp_dir / "tail_alpha.mov"

    try:
        # Body: video from start to split_point
        body_result = run([
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-t", str(split_point),
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-an", str(body_path),
        ])
        if body_result.returncode != 0 or not body_path.is_file():
            fail("Failed to create BODY.\n" + (body_result.stdout or "").strip())
        update_progress(25, "processing", "Body done.")

        # Tail: last N seconds
        tail_result = run([
            "ffmpeg", "-y",
            "-ss", str(split_point), "-i", str(input_path),
            "-t", str(tail_len),
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-an", str(tail_path),
        ])
        if tail_result.returncode != 0 or not tail_path.is_file():
            fail("Failed to create TAIL.\n" + (tail_result.stdout or "").strip())
        update_progress(50, "processing", "Tail done.")

        # Tail with alpha fade-out
        tail_alpha_result = run([
            "ffmpeg", "-y",
            "-i", str(tail_path),
            "-vf", f"format=rgba,fade=t=out:st={fade_start}:d={fade_duration}:alpha=1",
            "-c:v", "qtrle", str(tail_alpha_path),
        ])
        if tail_alpha_result.returncode != 0 or not tail_alpha_path.is_file():
            fail("Failed to create TAIL alpha.\n" + (tail_alpha_result.stdout or "").strip())
        update_progress(75, "processing", "Tail alpha done.")

        # Final: overlay tail_alpha on body, scale to 1920x1080
        final_result = run([
            "ffmpeg", "-y",
            "-i", str(body_path),
            "-i", str(tail_alpha_path),
            "-filter_complex",
            "[0:v][1:v]overlay=0:0:eof_action=pass,scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1[v]",
            "-map", "[v]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-movflags", "+faststart",
            str(output_path),
        ])
        if final_result.returncode != 0 or not output_path.is_file():
            fail("Failed to create FINAL overlay.\n" + (final_result.stdout or "").strip())
        update_progress(90, "processing", "Final render done.")

        size_bytes = output_path.stat().st_size

        print(json.dumps({
            "ok": True,
            "message": "Seamless preprocess succeeded.",
            "input_file": str(input_path),
            "output_file": str(output_path),
            "duration": duration,
            "split_point": split_point,
            "tail_len": tail_len,
            "fade_start": fade_start,
            "fade_end": fade_end,
            "fade_duration": fade_duration,
            "size_bytes": size_bytes,
        }, ensure_ascii=False))

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
