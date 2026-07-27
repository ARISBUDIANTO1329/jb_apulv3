#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import sys
import json
import os

FFPROBE = "ffprobe"


def get_video_duration(video_path: str) -> float:
    """
    Mengambil durasi video (DETIK) menggunakan ffprobe.
    Return: float (detik)
    """
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Intro video tidak ditemukan: {video_path}")

    cmd = [
        FFPROBE,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "format=duration",
        "-of", "json",
        video_path
    ]

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(f"ffprobe error: {result.stderr}")

    data = json.loads(result.stdout)

    if "format" not in data or "duration" not in data["format"]:
        raise ValueError("Gagal membaca durasi video")

    duration = float(data["format"]["duration"])

    if duration <= 0:
        raise ValueError("Durasi intro tidak valid")

    return duration


def main():
    """
    CLI usage:
    intro_builder.py <intro_video_path>

    Output (STDOUT):
    {
        "intro_duration": <float>
    }
    """
    if len(sys.argv) != 2:
        print("Usage: intro_builder.py <intro_video_path>", file=sys.stderr)
        sys.exit(1)

    intro_path = sys.argv[1]

    try:
        intro_duration = get_video_duration(intro_path)
    except Exception as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    # Output JSON (aman untuk diparse orchestrator)
    print(json.dumps({
        "intro_duration": intro_duration
    }))


if __name__ == "__main__":
    main()
