#!/usr/bin/env python3
"""
MERGE VIDEO WORKER - JB APUL v3
Randomly selects and merges multiple raw videos with transitions.
Used for Dynamic Video mode.
Ported from v2 with v3 path conventions.
"""

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
FPS = 30
AUDIO_RATE = 44100


def emit(payload, exit_code=0):
    print(json.dumps(payload, ensure_ascii=False))
    sys.exit(exit_code)


def fail(message, code=1, **extra):
    payload = {"ok": False, "message": message}
    payload.update(extra)
    emit(payload, code)


def run_command(command):
    return subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)


def ffprobe_duration(video_path):
    command = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    result = run_command(command)
    if result.returncode != 0:
        raise RuntimeError("Failed to read video duration: " + (result.stdout or "").strip())
    try:
        return float((result.stdout or "").strip())
    except Exception as exc:
        raise RuntimeError("Invalid duration from ffprobe.") from exc


def list_videos(input_folder):
    folder = Path(input_folder)
    if not folder.exists() or not folder.is_dir():
        raise ValueError(f"Input folder not found: {folder}")
    videos = [
        path for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    ]
    return sorted(videos)


def clean_temp(temp_dir):
    temp_dir.mkdir(parents=True, exist_ok=True)
    for item in temp_dir.iterdir():
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)


def parse_resolution(value):
    try:
        width, height = value.lower().split("x", 1)
        width, height = int(width), int(height)
    except Exception:
        raise ValueError("Resolution must be WIDTHxHEIGHT, e.g. 1920x1080.")
    if width < 100 or height < 100:
        raise ValueError("Resolution too small.")
    return width, height


def normalize_video(source_path, output_path, width, height, slow_enabled, speed, logs):
    source_duration = ffprobe_duration(source_path)
    output_duration = source_duration / speed if slow_enabled else source_duration

    video_filter = (
        f"fps={FPS},"
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"setsar=1,"
        f"format=yuv420p"
    )
    if slow_enabled:
        video_filter += f",setpts=PTS/{speed}"

    inputs = [
        "-i", str(source_path),
        "-f", "lavfi", "-t", str(output_duration),
        "-i", f"anullsrc=channel_layout=stereo:sample_rate={AUDIO_RATE}",
    ]

    audio_filter = f"[1:a]aformat=sample_fmts=fltp:sample_rates={AUDIO_RATE}:channel_layouts=stereo"
    filter_complex = f"[0:v]{video_filter}[v];{audio_filter}[a]"

    command = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-profile:v", "main", "-level", "4.1",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(output_path),
    ]

    result = run_command(command)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg normalize failed: {(result.stdout or '')[-500:]}")
    logs.append(f"Normalized: {source_path.name} -> {output_path.name}")


def concat_videos(segment_paths, output_path, transition_enabled, transition_name, transition_duration, logs):
    if not transition_enabled or transition_duration <= 0:
        # Simple concat without transitions
        list_file = output_path.parent / "_concat_list.txt"
        list_file.write_text(
            "\n".join(f"file '{p}'" for p in segment_paths),
            encoding="utf-8",
        )
        command = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            str(output_path),
        ]
        result = run_command(command)
        list_file.unlink(missing_ok=True)
    else:
        # Concat with xfade transitions
        if len(segment_paths) < 2:
            raise ValueError("Need at least 2 segments for transitions")

        inputs = []
        for p in segment_paths:
            inputs.extend(["-i", str(p)])

        # Build xfade filter chain
        filter_parts = []
        current = "[0:v]"
        total_duration = 0

        for i in range(1, len(segment_paths)):
            seg_dur = ffprobe_duration(segment_paths[i - 1])
            offset = max(0, seg_dur - transition_duration)
            next_in = f"[{i}:v]"

            if i == 1:
                out = "[vout]" if i == len(segment_paths) - 1 else f"[v{i}]"
            else:
                out = "[vout]" if i == len(segment_paths) - 1 else f"[v{i}]"

            filter_parts.append(
                f"{current}{next_in}xfade=transition={transition_name}:"
                f"duration={transition_duration}:offset={offset:.3f}{out}"
            )
            current = out
            total_duration += seg_dur - transition_duration

        # Audio crossfade
        audio_parts = []
        current_a = "[0:a]"
        for i in range(1, len(segment_paths)):
            next_a = f"[{i}:a]"
            out_a = "[aout]" if i == len(segment_paths) - 1 else f"[a{i}]"
            audio_parts.append(f"{current_a}{next_a}acrossfade=d={transition_duration}{out_a}")
            current_a = out_a

        filter_complex = ";".join(filter_parts + audio_parts)

        command = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path),
        ]
        result = run_command(command)

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg concat failed: {(result.stdout or '')[-500:]}")
    logs.append(f"Concatenated {len(segment_paths)} segments -> {output_path.name}")


def main():
    parser = argparse.ArgumentParser(description="Dynamic Video Merge Worker")
    parser.add_argument("--channel-id", required=True, type=int)
    parser.add_argument("--job-id", required=True, type=int)
    parser.add_argument("--input-folder", required=True)
    parser.add_argument("--output-file", required=True)
    parser.add_argument("--temp-dir", required=True)
    parser.add_argument("--count", required=True, type=int, help="Number of raw videos to merge")
    parser.add_argument("--resolution", default="1920x1080")
    parser.add_argument("--transition-enabled", type=int, default=1)
    parser.add_argument("--transition-name", default="fade")
    parser.add_argument("--transition-duration", type=float, default=1.0)
    parser.add_argument("--slow-enabled", type=int, default=0)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=None)

    args = parser.parse_args()

    if args.seed:
        random.seed(args.seed)

    logs = []
    width, height = parse_resolution(args.resolution)

    try:
        videos = list_videos(args.input_folder)
        if len(videos) < 2:
            fail(f"Need at least 2 videos in {args.input_folder}, found {len(videos)}")

        count = min(args.count, len(videos))
        selected = random.sample(videos, count)
        logs.append(f"Selected {count} videos: {[v.name for v in selected]}")

        temp_dir = Path(args.temp_dir)
        clean_temp(temp_dir)

        # Normalize each video
        normalized = []
        for i, video in enumerate(selected):
            norm_path = temp_dir / f"norm_{i:03d}.mp4"
            normalize_video(
                video, norm_path, width, height,
                bool(args.slow_enabled), args.speed, logs,
            )
            normalized.append(norm_path)

        # Concat
        output_path = Path(args.output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        concat_videos(
            normalized, output_path,
            bool(args.transition_enabled),
            args.transition_name,
            args.transition_duration,
            logs,
        )

        if not output_path.exists() or output_path.stat().st_size < 1024:
            fail("Output file is too small or missing")

        # Cleanup
        clean_temp(temp_dir)
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)

        emit({
            "ok": True,
            "message": f"Dynamic video created: {output_path.name}",
            "output_file": str(output_path),
            "selected_files": [v.name for v in selected],
            "logs": logs,
        })

    except Exception as exc:
        fail(str(exc), logs=logs)


if __name__ == "__main__":
    main()
