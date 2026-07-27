#!/usr/bin/env python3
"""
Thumbnail Generator
Creates YouTube thumbnails with text overlay and channel branding.

Usage:
    python3 thumbnail_generator.py --title "Relaxing Ocean Sounds" --channel NUVORA --output thumb.jpg
"""

import argparse
import json
import os
import sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import random


# Color palettes per channel
PALETTES = {
    1: {  # NUVORA - Ocean blues
        "bg_colors": [(0, 40, 80), (0, 60, 120), (0, 80, 160)],
        "accent": (0, 180, 255),
        "text_color": (255, 255, 255),
        "overlay_color": (0, 30, 60, 180),
    },
    2: {  # Healing Aura Lab - Warm purples
        "bg_colors": [(60, 20, 80), (80, 30, 100), (100, 40, 120)],
        "accent": (200, 150, 255),
        "text_color": (255, 255, 255),
        "overlay_color": (40, 15, 60, 180),
    },
    3: {  # Harmonia Field - Nature greens
        "bg_colors": [(20, 60, 40), (30, 80, 50), (40, 100, 60)],
        "accent": (100, 220, 150),
        "text_color": (255, 255, 255),
        "overlay_color": (15, 45, 30, 180),
    },
    4: {  # PURE HARMONY - Spiritual golds
        "bg_colors": [(60, 40, 10), (80, 50, 15), (100, 60, 20)],
        "accent": (255, 200, 100),
        "text_color": (255, 255, 255),
        "overlay_color": (45, 30, 10, 180),
    },
}

# Fallback if no font found
DEFAULT_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]


def find_font(size: int) -> ImageFont.FreeTypeFont:
    """Find a usable font."""
    for path in DEFAULT_FONT_PATHS:
        if os.path.isfile(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def create_gradient_background(width: int, height: int, colors: list) -> Image.Image:
    """Create a gradient background."""
    img = Image.new('RGB', (width, height))
    draw = ImageDraw.Draw(img)
    
    # Random gradient direction
    if random.random() > 0.5:
        # Top to bottom
        for y in range(height):
            ratio = y / height
            r = int(colors[0][0] * (1 - ratio) + colors[1][0] * ratio)
            g = int(colors[0][1] * (1 - ratio) + colors[1][1] * ratio)
            b = int(colors[0][2] * (1 - ratio) + colors[1][2] * ratio)
            draw.line([(0, y), (width, y)], fill=(r, g, b))
    else:
        # Diagonal
        for y in range(height):
            for x in range(width):
                ratio = (x + y) / (width + height)
                r = int(colors[0][0] * (1 - ratio) + colors[2][0] * ratio)
                g = int(colors[0][1] * (1 - ratio) + colors[2][1] * ratio)
                b = int(colors[0][2] * (1 - ratio) + colors[2][2] * ratio)
                img.putpixel((x, y), (r, g, b))
    
    return img


def add_glow_circles(img: Image.Image, accent_color: tuple, count: int = 3) -> Image.Image:
    """Add decorative glow circles."""
    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    
    for _ in range(count):
        x = random.randint(0, img.width)
        y = random.randint(0, img.height)
        radius = random.randint(50, 200)
        alpha = random.randint(20, 60)
        color = (*accent_color, alpha)
        draw.ellipse(
            [x - radius, y - radius, x + radius, y + radius],
            fill=color
        )
    
    # Blur the circles
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=30))
    
    # Composite
    result = img.copy()
    result.paste(overlay, (0, 0), overlay)
    return result


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list:
    """Wrap text to fit within max_width."""
    words = text.split()
    lines = []
    current_line = ""
    
    for word in words:
        test_line = f"{current_line} {word}".strip()
        bbox = font.getbbox(test_line)
        text_width = bbox[2] - bbox[0]
        
        if text_width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    
    if current_line:
        lines.append(current_line)
    
    return lines


def generate_thumbnail(
    title: str,
    channel_id: int,
    output_path: str,
    channel_name: str = None,
    subtitle: str = None,
    width: int = 1280,
    height: int = 720
) -> bool:
    """Generate a YouTube thumbnail."""
    
    palette = PALETTES.get(channel_id, PALETTES[1])
    
    # Create background
    bg = create_gradient_background(width, height, palette["bg_colors"])
    
    # Add glow effects
    bg = add_glow_circles(bg, palette["accent"], count=random.randint(2, 4))
    
    # Create overlay for text area
    overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    
    # Semi-transparent overlay at bottom
    draw.rectangle(
        [0, height // 3, width, height],
        fill=palette["overlay_color"]
    )
    
    # Composite
    bg.paste(overlay, (0, 0), overlay)
    draw = ImageDraw.Draw(bg)
    
    # Load fonts
    title_font = find_font(64)
    subtitle_font = find_font(36)
    channel_font = find_font(28)
    
    # Draw title
    margin = 60
    max_text_width = width - margin * 2
    title_lines = wrap_text(title.upper(), title_font, max_text_width)
    
    y_offset = height // 2 - 40
    for line in title_lines[:3]:  # Max 3 lines
        bbox = title_font.getbbox(line)
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) // 2
        
        # Shadow
        draw.text((x + 3, y_offset + 3), line, font=title_font, fill=(0, 0, 0, 128))
        # Main text
        draw.text((x, y_offset), line, font=title_font, fill=palette["text_color"])
        
        y_offset += bbox[3] - bbox[1] + 10
    
    # Draw subtitle if provided
    if subtitle:
        y_offset += 20
        bbox = subtitle_font.getbbox(subtitle)
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) // 2
        draw.text((x, y_offset), subtitle, font=subtitle_font, fill=palette["accent"])
    
    # Draw channel name
    if channel_name:
        channel_text = f"@{channel_name}"
        bbox = channel_font.getbbox(channel_text)
        text_width = bbox[2] - bbox[0]
        draw.text(
            (width - text_width - margin, height - 50),
            channel_text,
            font=channel_font,
            fill=(*palette["accent"], 200)
        )
    
    # Draw accent line
    line_y = height // 3
    draw.line(
        [(margin, line_y), (width - margin, line_y)],
        fill=palette["accent"],
        width=3
    )
    
    # Save
    bg = bg.convert('RGB')
    bg.save(output_path, 'JPEG', quality=95)
    
    return True


def main():
    parser = argparse.ArgumentParser(description='Thumbnail Generator')
    parser.add_argument('--title', required=True, help='Thumbnail title text')
    parser.add_argument('--channel-id', type=int, required=True, help='Channel ID (1-4)')
    parser.add_argument('--channel-name', default=None, help='Channel name')
    parser.add_argument('--subtitle', default=None, help='Subtitle text')
    parser.add_argument('--output', required=True, help='Output file path')
    parser.add_argument('--width', type=int, default=1280, help='Width')
    parser.add_argument('--height', type=int, default=720, help='Height')
    parser.add_argument('--count', type=int, default=1, help='Generate multiple thumbnails')
    args = parser.parse_args()
    
    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    
    results = []
    
    if args.count == 1:
        success = generate_thumbnail(
            args.title,
            args.channel_id,
            args.output,
            args.channel_name,
            args.subtitle,
            args.width,
            args.height
        )
        if success:
            size_kb = os.path.getsize(args.output) / 1024
            results.append({
                "file": args.output,
                "size_kb": round(size_kb, 1)
            })
    else:
        # Generate multiple variations
        base, ext = os.path.splitext(args.output)
        for i in range(args.count):
            output_path = f"{base}_{i+1}{ext}"
            success = generate_thumbnail(
                args.title,
                args.channel_id,
                output_path,
                args.channel_name,
                args.subtitle,
                args.width,
                args.height
            )
            if success:
                size_kb = os.path.getsize(output_path) / 1024
                results.append({
                    "file": output_path,
                    "size_kb": round(size_kb, 1)
                })
    
    output = {
        "ok": True,
        "thumbnails": results,
        "total": len(results)
    }
    
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
