"""
Central configuration for the Kids Cartoon Video Generator.
Optimized for Free Cloud Tiers (Low Memory & CPU).
"""

import os

# ---------------------------------------------------------------------------
# API KEYS
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# ---------------------------------------------------------------------------
# VIDEO SETTINGS (Optimized for Free Server Tier)
# ---------------------------------------------------------------------------
VIDEO_WIDTH = 640            # تخفيض الأبعاد لتخفيف المعالجة
VIDEO_HEIGHT = 360           # أبعاد مريحة جداً للسيرفرات وتظل واضحة
FPS = 12                     # تقليص الإطارات لتسريع الرندرة 3 أضعاف
TARGET_TOTAL_SECONDS = 45    # جعل القصة الأولى حوالي 45 ثانية لتجربة ثبات النظام
MIN_SCENES = 3               # تقليل عدد المشاهد في البداية
MAX_SCENES = 4

# ---------------------------------------------------------------------------
# TTS SETTINGS (edge-tts, 100% free)
# ---------------------------------------------------------------------------
ARABIC_VOICES = {
    "female_expressive": "ar-EG-SalmaNeural",
    "male_warm": "ar-EG-ShakirNeural",
    "female_saudi": "ar-SA-ZariyahNeural",
    "male_saudi": "ar-SA-HamedNeural",
}
DEFAULT_VOICE = ARABIC_VOICES["female_expressive"]
TTS_RATE = "+0%"
TTS_PITCH = "+0Hz"

# ---------------------------------------------------------------------------
# IMAGE GENERATION (Pollinations.ai)
# ---------------------------------------------------------------------------
POLLINATIONS_BASE_URL = "https://pollinations.ai"
IMAGE_MODEL = "flux"
IMAGE_STYLE_SUFFIX = (
    "children's cartoon illustration, flat colors, thick clean outlines, "
    "storybook style, soft lighting, simple background, no text, no watermark, no logo"
)

# ---------------------------------------------------------------------------
# SUBTITLES
# ---------------------------------------------------------------------------
SUBTITLE_FONT_PATH = None
SUBTITLE_FONT_SIZE = 24       # تصغير حجم الخط ليتناسب مع الأبعاد الجديدة
SUBTITLE_COLORS = ["#FFD93D", "#6BCB77", "#4D96FF", "#FF6B6B"]
SUBTITLE_STROKE_COLOR = "#1A1A1A"
SUBTITLE_STROKE_WIDTH = 2
SUBTITLE_MARGIN_BOTTOM = 30

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
# AUTOMATED SHORTS EXTRACTOR (Optimized)
# ---------------------------------------------------------------------------
SHORTS_DIRNAME = "shorts_output"
SHORTS_OUTPUT_DIR = os.path.join(WORKDIR, SHORTS_DIRNAME)
os.makedirs(SHORTS_OUTPUT_DIR, exist_ok=True)

SHORTS_MIN_SECONDS = 10
SHORTS_MAX_SECONDS = 25
SHORTS_TARGET_MIN_CLIPS = 1
SHORTS_TARGET_MAX_CLIPS = 2

# Vertical Shorts Resolution (Optimized)
SHORTS_WIDTH = 480
SHORTS_HEIGHT = 854

# ---------------------------------------------------------------------------
# HARD PROJECT RULE
# ---------------------------------------------------------------------------
NO_BACKGROUND_MUSIC = True
