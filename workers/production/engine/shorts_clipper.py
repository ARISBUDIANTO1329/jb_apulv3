#!/usr/bin/env python3
"""
Shorts Auto-Clipper
Extracts 30-60 second vertical clips from long videos for YouTube Shorts.

Usage:
    python3 shorts_clipper.py --input video.mp4 --output-dir ./shorts --count 5
    
Output: 1080x1920 (9:16) vertical clips with optional text overlay
"""

import argparse
import json
import os
import random
import subprocess
import sys
from pathlib import Path


def get_video_duration(input_path: str) -> float:
    """Get video duration in seconds."""
    cmd = [
        'ffprobe', '-v', 'quiet',
        '-show_entries', 'format=duration',
        '-of', 'csv=p=0',
        input_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(result.stdout.strip())


def extract_clip(
    input_path: str,
    output_path: str,
    start_time: float,
    duration: float,
    text_overlay: str = None,
    channel_name: str = None
) -> bool:
    """Extract a vertical clip from the input video."""
    
    # Build filter chain
    filters = []
    
    # Scale to 9:16 vertical (1080x1920)
    # First crop to square-ish from center, then scale
    filters.append(
        "crop=ih*9/16:ih:iw/2-ih*9/16/2:0,"
        "scale=1080:1920:flags=lanczos"
    )
    
    # Add subtle vignette for cinematic look
    filters.append("vignette=PI/4")
    
    # Add text overlay if provided
    if text_overlay:
        # Escape special characters for ffmpeg
        safe_text = text_overlay.replace("'", "\\'").replace(":", "\\:")
        filters.append(
            f"drawtext=text='{safe_text}':"
            "fontsize=48:fontcolor=white:"
            "borderw=3:bordercolor=black:"
            "x=(w-text_w)/2:y=h-th-80:"
            "fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        )
    
    # Subscribe watermark
    if channel_name:
        safe_channel = channel_name.replace("'", "\\'").replace(":", "\\:")
        filters.append(
            f"drawtext=text='Subscribe @ {safe_channel}':"
            "fontsize=32:fontcolor=white@0.8:"
            "borderw=2:bordercolor=black@0.5:"
            "x=(w-text_w)/2:y=h-th-30:"
            "fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        )
    
    filter_str = ",".join(filters)
    
    cmd = [
        'ffmpeg', '-y',
        '-ss', str(start_time),
        '-i', input_path,
        '-t', str(duration),
        '-vf', filter_str,
        '-c:v', 'libx264',
        '-preset', 'medium',
        '-crf', '23',
        '-c:a', 'aac',
        '-b:a', '128k',
        '-ar', '44100',
        '-movflags', '+faststart',
        '-metadata', f'title={text_overlay or "Relaxing Music"}',
        output_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def find_interesting_segments(
    input_path: str,
    duration: float,
    clip_count: int,
    clip_duration: float
) -> list:
    """Find interesting time segments for clips.
    
    Strategy: sample evenly from the video, avoiding the very start and end.
    """
    segments = []
    
    # Skip first 30s and last 30s (usually intro/outro)
    safe_start = 30
    safe_end = duration - 30
    
    if safe_end <= safe_start:
        # Video too short, use full duration
        safe_start = 0
        safe_end = duration
    
    available_duration = safe_end - safe_start
    
    if clip_count == 1:
        # Single clip: pick from middle
        start = safe_start + available_duration / 2 - clip_duration / 2
        segments.append(max(0, start))
    else:
        # Multiple clips: evenly space them
        step = available_duration / (clip_count + 1)
        for i in range(clip_count):
            start = safe_start + step * (i + 1) - clip_duration / 2
            # Add slight randomness
            start += random.uniform(-5, 5)
            start = max(safe_start, min(safe_end - clip_duration, start))
            segments.append(start)
    
    return segments


def generate_clip_titles(
    channel_name: str,
    count: int,
    base_title: str = None
) -> list:
    """Generate engaging titles for Shorts."""
    
    templates = [
        "30 Seconds of Pure Calm 🌊",
        "Try Not to Relax Challenge 😌",
        "This Sound Will Put You to Sleep in 60 Seconds 💤",
        "The Most Relaxing Sound on YouTube 🎵",
        "POV: You Found Inner Peace 🧘",
        "Close Your Eyes and Listen... 🌙",
        "Your Anxiety Will Disappear in 30 Seconds ✨",
        "The Ultimate Sleep Hack 💫",
        "Nature's White Noise 🌧️",
        "Instant Calm - Just Press Play ▶️",
        "60 Seconds of Heaven 🌅",
        "The Sound That Cures Insomnia 😴",
        "Relax Your Mind in 30 Seconds 🧠",
        "Deep Sleep in 60 Seconds Guaranteed 💤",
        "The Most Soothing Sound You'll Ever Hear 🎶",
    ]
    
    titles = []
    for i in range(count):
        if base_title:
            title = f"{base_title} #{i+1}"
        else:
            title = random.choice(templates)
            templates.remove(title)  # Don't repeat
            if not templates:
                templates = [
                    "More Calming Sounds 🌊",
                    "Another 30 Seconds of Peace ✨",
                    "Sleep Better Tonight 💤",
                ]
        titles.append(title)
    
    return titles


def main():
    parser = argparse.ArgumentParser(description='Shorts Auto-Clipper')
    parser.add_argument('--input', required=True, help='Input video path')
    parser.add_argument('--output-dir', required=True, help='Output directory')
    parser.add_argument('--count', type=int, default=5, help='Number of clips')
    parser.add_argument('--duration', type=float, default=45, help='Clip duration (30-60s)')
    parser.add_argument('--channel-name', default=None, help='Channel name for watermark')
    parser.add_argument('--base-title', default=None, help='Base title for clips')
    parser.add_argument('--seed', type=int, default=None, help='Random seed')
    args = parser.parse_args()
    
    if args.seed:
        random.seed(args.seed)
    
    # Validate
    if not os.path.isfile(args.input):
        print(json.dumps({"ok": False, "error": f"Input not found: {args.input}"}))
        sys.exit(1)
    
    # Clamp duration to 30-60s
    clip_duration = max(30, min(60, args.duration))
    
    # Create output dir
    os.makedirs(args.output_dir, exist_ok=True)
    
    # Get video duration
    video_duration = get_video_duration(args.input)
    
    if video_duration < 60:
        print(json.dumps({"ok": False, "error": f"Video too short ({video_duration}s), need at least 60s"}))
        sys.exit(1)
    
    # Find segments
    segments = find_interesting_segments(
        args.input, video_duration, args.count, clip_duration
    )
    
    # Generate titles
    titles = generate_clip_titles(
        args.channel_name or "Channel",
        args.count,
        args.base_title
    )
    
    # Extract clips
    results = []
    for i, (start_time, title) in enumerate(zip(segments, titles)):
        output_filename = f"short_{i+1:02d}_{int(start_time)}.mp4"
        output_path = os.path.join(args.output_dir, output_filename)
        
        text = title.split(" 🌊")[0].split(" 😌")[0].split(" 💤")[0]  # Remove emojis for overlay
        
        success = extract_clip(
            args.input,
            output_path,
            start_time,
            clip_duration,
            text_overlay=text,
            channel_name=args.channel_name
        )
        
        if success and os.path.isfile(output_path):
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            results.append({
                "file": output_path,
                "title": title,
                "start_time": round(start_time, 1),
                "duration": clip_duration,
                "size_mb": round(size_mb, 1)
            })
    
    output = {
        "ok": True,
        "source": args.input,
        "source_duration": round(video_duration, 1),
        "clips": results,
        "total_clips": len(results)
    }
    
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
