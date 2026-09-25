"""
Central configuration for the Kids Cartoon Video Generator.
No paid/watermarked services are referenced anywhere in this project.
"""

import os

# ---------------------------------------------------------------------------
# API KEYS (all optional except the LLM key you choose to use)
# Set these as environment variables, or in Streamlit Cloud -> Settings -> Secrets
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")          # free tier: https://google.com
# Pollinations.ai and edge-tts require NO API key at all.

# ---------------------------------------------------------------------------
# VIDEO SETTINGS
# ---------------------------------------------------------------------------
VIDEO_WIDTH = 1024
VIDEO_HEIGHT = 576          # 16:9, matches Pollinations default aspect well
FPS = 24
TARGET_TOTAL_SECONDS = 120   # ~2 minutes
MIN_SCENES = 6
MAX_SCENES = 10

# ---------------------------------------------------------------------------
# TTS SETTINGS (edge-tts, 100% free, no watermark, no key needed)
# ---------------------------------------------------------------------------
# A few natural-sounding Arabic voices available in edge-tts:
ARABIC_VOICES = {
    "female_expressive": "ar-EG-SalmaNeural",
    "male_warm": "ar-EG-ShakirNeural",
    "female_saudi": "ar-SA-ZariyahNeural",
    "male_saudi": "ar-SA-HamedNeural",
}
DEFAULT_VOICE = ARABIC_VOICES["female_expressive"]
TTS_RATE = "+0%"     # e.g. "+10%" for faster narration
TTS_PITCH = "+0Hz"

# ---------------------------------------------------------------------------
# IMAGE GENERATION (Pollinations.ai - free, no key, no watermark)
# ---------------------------------------------------------------------------
POLLINATIONS_BASE_URL = "https://pollinations.ai"
IMAGE_MODEL = "flux"        # good free model on Pollinations for illustration style
IMAGE_STYLE_SUFFIX = (
    "children's cartoon illustration, flat colors, thick clean outlines, "
    "storybook style, soft lighting, simple background, no text, no watermark, no logo"
)

# ---------------------------------------------------------------------------
# SUBTITLES
# ---------------------------------------------------------------------------
SUBTITLE_FONT_PATH = None    # set to a .ttf path with Arabic glyph support if you have one
SUBTITLE_FONT_SIZE = 44
SUBTITLE_COLORS = ["#FFD93D", "#6BCB77", "#4D96FF", "#FF6B6B", "#C780FA"]  # rotates per scene
SUBTITLE_STROKE_COLOR = "#1A1A1A"
SUBTITLE_STROKE_WIDTH = 3
SUBTITLE_MARGIN_BOTTOM = 60

# ---------------------------------------------------------------------------
# WORKING DIRECTORIES
# ---------------------------------------------------------------------------
WORKDIR = os.environ.get("KVG_WORKDIR", "./workdir")
IMAGES_DIR = os.path.join(WORKDIR, "images")
AUDIO_DIR = os.path.join(WORKDIR, "audio")
OUTPUT_DIR = os.path.join(WORKDIR, "output")

for d in (WORKDIR, IMAGES_DIR, AUDIO_DIR, OUTPUT_DIR):
    os.makedirs(d, exist_ok=True)

# ---------------------------------------------------------------------------
# AUTOMATED SHORTS EXTRACTOR
# ---------------------------------------------------------------------------
SHORTS_DIRNAME = "shorts_output"
SHORTS_OUTPUT_DIR = os.path.join(WORKDIR, SHORTS_DIRNAME)
os.makedirs(SHORTS_OUTPUT_DIR, exist_ok=True)

SHORTS_MIN_SECONDS = 30
SHORTS_MAX_SECONDS = 50
SHORTS_TARGET_MIN_CLIPS = 3
SHORTS_TARGET_MAX_CLIPS = 4

# Vertical 9:16 output resolution for YouTube Shorts / TikTok
SHORTS_WIDTH = 1080
SHORTS_HEIGHT = 1920

# ---------------------------------------------------------------------------
# HARD PROJECT RULE — enforced in code, not just in prompts:
# NO_BACKGROUND_MUSIC must stay True. video_assembler.py never mixes in a
# music track even if this is somehow flipped; it is kept here only as a
# documented, explicit guardrail. shorts_extractor.py only ever takes
# sub-clips of the already-rendered long video (voice + burned-in captions
# already in the frames), so no shorts code path can introduce music either.
# ---------------------------------------------------------------------------
NO_BACKGROUND_MUSIC = True
