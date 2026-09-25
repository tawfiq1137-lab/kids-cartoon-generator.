"""
subtitle_utils.py
------------------
Renders each scene's Arabic narration as a colorful subtitle image (PNG with
transparency) using Pillow + arabic_reshaper + python-bidi for correct
right-to-left shaping. This avoids depending on ImageMagick (which moviepy's
TextClip needs and which is unreliable to install on Streamlit Cloud) while
still giving full control over color/outline/positioning.
"""

import os
import textwrap

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

from . import config


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    if config.SUBTITLE_FONT_PATH and os.path.exists(config.SUBTITLE_FONT_PATH):
        return ImageFont.truetype(config.SUBTITLE_FONT_PATH, size)
    # Fallback: Pillow's bundled DejaVuSans does NOT support Arabic glyphs well.
    # Users should supply a proper Arabic .ttf (e.g. Noto Naskh Arabic) via
    # config.SUBTITLE_FONT_PATH for correct rendering — see README setup steps.
    try:
        return ImageFont.truetype("NotoNaskhArabic-Regular.ttf", size)
    except Exception:  # noqa: BLE001
        return ImageFont.load_default()


def _shape_arabic(text: str) -> str:
    reshaped = arabic_reshaper.reshape(text)
    return get_display(reshaped)


def render_subtitle_png(text: str, scene_index: int, out_path: str) -> str:
    """
    Renders `text` as a transparent PNG the same width as the video, with
    wrapped, shaped Arabic text near the bottom, colored per scene.
    """
    width, height = config.VIDEO_WIDTH, config.VIDEO_HEIGHT
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font = _load_font(config.SUBTITLE_FONT_SIZE)
    color = config.SUBTITLE_COLORS[scene_index % len(config.SUBTITLE_COLORS)]
    stroke_color = config.SUBTITLE_STROKE_COLOR
    stroke_width = config.SUBTITLE_STROKE_WIDTH

    wrapped_lines = textwrap.wrap(text, width=28) or [text]
    shaped_lines = [_shape_arabic(line) for line in wrapped_lines]

    line_heights = []
    line_widths = []
    for line in shaped_lines:
        bbox = draw.textbbox((0, 0), line, font=font, stroke_width=stroke_width)
        line_widths.append(bbox[2] - bbox[0])
        line_heights.append(bbox[3] - bbox[1])

    total_text_height = sum(line_heights) + (len(shaped_lines) - 1) * 10
    y = height - config.SUBTITLE_MARGIN_BOTTOM - total_text_height

    for line, lw, lh in zip(shaped_lines, line_widths, line_heights):
        x = (width - lw) / 2
        draw.text(
            (x, y),
            line,
            font=font,
            fill=color,
            stroke_width=stroke_width,
            stroke_fill=stroke_color,
        )
        y += lh + 10

    img.save(out_path)
    return out_path


def render_all_subtitles(scenes, subtitles_dir: str) -> list:
    os.makedirs(subtitles_dir, exist_ok=True)
    paths = []
    for scene in scenes:
        out_path = os.path.join(subtitles_dir, f"subtitle_{scene.index:02d}.png")
        render_subtitle_png(scene.narration_ar, scene.index, out_path)
        paths.append(out_path)
    return paths
