#!/usr/bin/env python3
"""
AUDIO ENGINE - JB APUL v3
Combines MP3 + SFX into a single audio track.
Ported from v2 with v3 path conventions.
"""

import os
import sys
import random
import subprocess
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import get_db, update_progress, append_log

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"
OPENING_SECONDS = 3


def get_duration(path: str) -> float:
    """Get media duration in seconds."""
    r = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    value = (r.stdout or "").strip()
    if r.returncode != 0 or not value:
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def run_ffmpeg(cmd: list):
    """Run FFmpeg command, exit on failure."""
    p = subprocess.run(cmd)
    if p.returncode != 0:
        sys.exit(1)


def main():
    if len(sys.argv) != 3:
        print("[AUDIO] Usage: audio_engine.py <job_id> <storage_path>")
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
        print(f"[AUDIO] Job {job_id} not found")
        sys.exit(1)

    update_progress(job_id, 5, "Audio: memuat job")
    append_log(job_id, "Audio: memuat job")
    print(f"[AUDIO] Audio: memuat job")

    if job["audio_status"] == "done":
        append_log(job_id, f"Job {job_id} already done, skip")
        print(f"[AUDIO] Job {job_id} already done, skip")
        sys.exit(0)

    channel_id = job["channel_id"]
    use_mp3 = not job["no_mp3"]
    use_sfx = not job["no_sfx"]
    duration_mode = job["duration_mode"]
    duration_manual = int(job["custom_duration"] or 0)
    mp3_filename = job.get("mp3_file") or ""
    mp3_mode = "filename" if mp3_filename else "random"
    mp3_count = int(job["num_songs"] or 0)

    mp3_file = None
    is_concat = False
    sfx_file = None

    # --- MP3 ---
    if use_mp3:
        mp3_dir = os.path.join(assets, "mp3", str(channel_id))
        if not os.path.isdir(mp3_dir):
            print("[AUDIO] MP3 folder not found, fallback silent")
            use_mp3 = False
        else:
            mp3_list = [
                os.path.join(mp3_dir, f)
                for f in os.listdir(mp3_dir)
                if f.lower().endswith(".mp3")
            ]
            if not mp3_list:
                print("[AUDIO] MP3 folder empty, fallback silent")
                use_mp3 = False

            if use_mp3:
                if mp3_mode == "filename":
                    mp3_file = os.path.join(mp3_dir, mp3_filename)
                    if not os.path.exists(mp3_file):
                        append_log(job_id, f"MP3 file not found: {mp3_file}")
                        print(f"[AUDIO] MP3 file not found: {mp3_file}")
                        sys.exit(1)
                elif duration_mode == "manual" and duration_manual > 0:
                    # AUTO-CALCULATE: pick MP3s until total >= target duration
                    is_concat = True
                    target_sec = duration_manual
                    append_log(job_id, f"Manual mode: target={target_sec}s, auto-calculating MP3 count")
                    print(f"[AUDIO] Manual mode: target={target_sec}s, auto-calculating MP3 count")

                    # Get durations of all MP3s
                    mp3_with_dur = []
                    for mp3_path in mp3_list:
                        dur = get_duration(mp3_path)
                        if dur > 0:
                            mp3_with_dur.append((mp3_path, dur))

                    if not mp3_with_dur:
                        print("[AUDIO] No valid MP3 files found")
                        use_mp3 = False
                    else:
                        # Shuffle and pick until total >= target
                        random.shuffle(mp3_with_dur)
                        chosen = []
                        total_dur = 0
                        idx = 0

                        while total_dur < target_sec:
                            if idx >= len(mp3_with_dur):
                                # Not enough unique MP3s, loop from beginning
                                random.shuffle(mp3_with_dur)
                                idx = 0
                            chosen.append(mp3_with_dur[idx])
                            total_dur += mp3_with_dur[idx][1]
                            idx += 1

                        append_log(job_id, f"Auto-picked {len(chosen)} MP3s, total={total_dur:.0f}s (target={target_sec}s)")

                        print(f"[AUDIO] Auto-picked {len(chosen)} MP3s, total={total_dur:.0f}s (target={target_sec}s)")

                        # Concat all chosen MP3s
                        list_file = tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".txt")
                        for mp3_path, _ in chosen:
                            list_file.write(f"file \'{mp3_path}\'\n")
                        list_file.close()

                        merged_mp3 = os.path.join(tmp_dir, f"_mp3_merge_{job_id}.wav")
                        run_ffmpeg([
                            FFMPEG, "-y",
                            "-f", "concat", "-safe", "0",
                            "-i", list_file.name,
                            "-c:a", "pcm_s16le",
                            merged_mp3,
                        ])
                        mp3_file = merged_mp3
                else:
                    # Mode "mp3": use num_songs as count
                    is_concat = True
                    chosen = random.sample(mp3_list, min(mp3_count, len(mp3_list)))
                    if not chosen:
                        print("[AUDIO] No MP3 selected")
                        use_mp3 = False
                    else:
                        list_file = tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".txt")
                        for f in chosen:
                            list_file.write(f"file \'{f}\'\n")
                        list_file.close()

                        merged_mp3 = os.path.join(tmp_dir, f"_mp3_merge_{job_id}.wav")
                        run_ffmpeg([
                            FFMPEG, "-y",
                            "-f", "concat", "-safe", "0",
                            "-i", list_file.name,
                            "-c:a", "pcm_s16le",
                            merged_mp3,
                        ])
                        mp3_file = merged_mp3

    # --- SFX ---
    if use_sfx:
        sfx_dir = os.path.join(assets, "sfx", str(channel_id))
        if not os.path.isdir(sfx_dir):
            print("[AUDIO] SFX folder not found")
            sys.exit(1)
        sfx_list = [
            os.path.join(sfx_dir, f)
            for f in os.listdir(sfx_dir)
            if f.lower().endswith((".mp3", ".wav"))
        ]
        if not sfx_list:
            print("[AUDIO] SFX folder empty")
            sys.exit(1)
        sfx_file = random.choice(sfx_list)
        append_log(job_id, f"SFX selected: {os.path.basename(sfx_file)}")
        print(f"[AUDIO] SFX selected: {os.path.basename(sfx_file)}")

    # --- Duration ---
    if duration_mode == "manual":
        final_duration = duration_manual
    elif use_mp3 and mp3_file:
        final_duration = int(get_duration(mp3_file))
    elif use_sfx and sfx_file:
        final_duration = int(get_duration(sfx_file))
    else:
        final_duration = duration_manual

    append_log(job_id, f"Target duration: {final_duration}s ({final_duration//3600}h{(final_duration%3600)//60}m{final_duration%60}s)")

    print(f"[AUDIO] Target duration: {final_duration}s ({final_duration//3600}h{(final_duration%3600)//60}m{final_duration%60}s)")
    mp3_yes = "yes" if use_mp3 else "no"
    sfx_yes = "yes" if use_sfx else "no"
    append_log(job_id, f"MP3: {mp3_yes} | SFX: {sfx_yes} | Mode: {duration_mode}")
    print(f"[AUDIO] MP3: {mp3_yes} | SFX: {sfx_yes} | Mode: {duration_mode}")

    # Fallback duration
    if final_duration <= 0:
        for fallback_dir_name in ["mp3", "sfx"]:
            fallback_dir = os.path.join(assets, fallback_dir_name, str(channel_id))
            if os.path.isdir(fallback_dir):
                fallback_files = [f for f in os.listdir(fallback_dir) if f.lower().endswith((".mp3", ".wav"))]
                if fallback_files:
                    final_duration = int(get_duration(os.path.join(fallback_dir, random.choice(fallback_files))))
                    if final_duration > 0:
                        break

    if final_duration <= 0:
        final_duration = 3600
        append_log(job_id, f"WARNING: using default duration {final_duration}s")
        print(f"[AUDIO] WARNING: using default duration {final_duration}s")

    update_progress(job_id, 20, "Audio: memproses audio")
    append_log(job_id, "Audio: memproses audio")
    print(f"[AUDIO] Audio: memproses audio")
    output_audio = os.path.join(tmp_dir, f"audio_{job_id}.wav")

    # --- Mix ---
    if use_mp3 and use_sfx and final_duration > OPENING_SECONDS:
        delay_ms = OPENING_SECONDS * 1000
        cmd = [FFMPEG, "-y"]
        cmd += ["-stream_loop", "-1", "-i", sfx_file]
        if not is_concat:
            cmd += ["-stream_loop", "-1"]
        cmd += [
            "-i", mp3_file,
            "-filter_complex",
            f"[1:a]adelay={delay_ms}|{delay_ms}[mp3d];[0:a][mp3d]amix=inputs=2",
            "-t", str(final_duration),
            "-c:a", "pcm_s16le", output_audio,
        ]
        run_ffmpeg(cmd)

    elif use_mp3:
        cmd = [FFMPEG, "-y"]
        if not is_concat:
            cmd += ["-stream_loop", "-1"]
        cmd += ["-i", mp3_file, "-t", str(final_duration), "-c:a", "pcm_s16le", output_audio]
        run_ffmpeg(cmd)

    elif use_sfx:
        run_ffmpeg([
            FFMPEG, "-y", "-stream_loop", "-1", "-i", sfx_file,
            "-t", str(final_duration), "-c:a", "pcm_s16le", output_audio,
        ])

    else:
        run_ffmpeg([
            FFMPEG, "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", str(final_duration), "-c:a", "pcm_s16le", output_audio,
        ])

    # --- Validate ---
    update_progress(job_id, 90, "Audio: validasi output")
    append_log(job_id, "Audio: validasi output")
    print(f"[AUDIO] Audio: validasi output")
    if not os.path.exists(output_audio) or os.path.getsize(output_audio) <= 1024:
        append_log(job_id, f"Output audio failed/too small: {output_audio}")
        print(f"[AUDIO] Output audio failed/too small: {output_audio}")
        sys.exit(1)

    cur.execute(
        "UPDATE production_jobs SET audio_status='done', audio_path=%s, updated_at=NOW() WHERE id=%s",
        (output_audio, job_id),
    )
    conn.commit()
    conn.close()

    size_mb = os.path.getsize(output_audio) / (1024*1024)
    append_log(job_id, f"Output: {os.path.basename(output_audio)} ({size_mb:.1f}MB)")
    print(f"[AUDIO] Output: {os.path.basename(output_audio)} ({size_mb:.1f}MB)")
    append_log(job_id, f"Job {job_id} DONE")
    print(f"[AUDIO] Job {job_id} DONE")
    sys.exit(0)


if __name__ == "__main__":
    main()
