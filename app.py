"""
Tool 1: English script -> ElevenLabs voice (fixed Voice ID) + word timestamps
        -> voiceover.mp3 + subtitles.srt -> 16:9 video (optional burned-in subtitles)
No background music. Optional very quiet ambient sound only.

Install:  pip install requests pillow "moviepy==1.0.3"
(moviepy needs ffmpeg installed on your system)
"""

import os
import glob
import json
import base64
import random
import textwrap
import requests
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    AudioFileClip, ImageClip, CompositeVideoClip,
    concatenate_videoclips, CompositeAudioClip,
)
import moviepy.audio.fx.all as afx

# ======================= الإعدادات (غيّرها هنا) =======================
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "PUT_YOUR_API_KEY_HERE")
VOICE_ID = "PUT_YOUR_FIXED_VOICE_ID_HERE"

MODEL_ID = "eleven_multilingual_v2"
VOICE_SETTINGS = {"stability": 0.60, "similarity_boost": 0.80, "style": 0.0}

SCRIPT_FILE = "script.txt"
IMAGES_DIR = "images"
AMBIENT_FILE = None
AMBIENT_VOLUME = 0.06
OUTPUT_AUDIO = "voiceover.mp3"
OUTPUT_SRT = "subtitles.srt"
OUTPUT_VIDEO = "final.mp4"

W, H, FPS = 1920, 1080, 24
SCENE_MIN, SCENE_MAX = 3.0, 5.0
ZOOM = 0.05

# --- إعدادات الترجمة ---
BURN_SUBTITLES = False      # True = حرق الترجمة على الفيديو | False = ملف SRT فقط (لـ CC في يوتيوب)
SUB_MAX_CHARS = 84          # أقصى عدد أحرف في الجملة الواحدة (سطرين)
SUB_LINE_WIDTH = 42         # عرض السطر الواحد بالأحرف
SUB_MAX_DURATION = 6.0      # أقصى مدة للجملة بالثواني
FONT_PATH = "arial.ttf"     # Windows: arial.ttf | Linux: /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf | Mac: /System/Library/Fonts/Helvetica.ttc
FONT_SIZE = 44
SUB_BOTTOM_MARGIN = 90      # المسافة من أسفل الشاشة
# =====================================================================


# ---------------------- 1) الصوت + التوقيتات ----------------------
def generate_voice_with_timestamps(text: str, mp3_path: str) -> dict:
    """يرسل النص إلى endpoint الخاص بالـ timestamps، يحفظ MP3، ويرجّع alignment."""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}/with-timestamps"
    headers = {"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"}
    payload = {"text": text, "model_id": MODEL_ID, "voice_settings": VOICE_SETTINGS}

    r = requests.post(url, headers=headers, json=payload, timeout=600)
    if r.status_code != 200:
        raise RuntimeError(f"ElevenLabs error {r.status_code}: {r.text}")

    data = r.json()
    with open(mp3_path, "wb") as f:
        f.write(base64.b64decode(data["audio_base64"]))
    print(f"[OK] Saved voiceover -> {mp3_path}")

    alignment = data["alignment"]  # يطابق النص الأصلي حرفًا بحرف
    with open("alignment.json", "w", encoding="utf-8") as f:  # للرجوع إليه عند الحاجة
        json.dump(alignment, f)
    return alignment


# ---------------------- 2) من الحروف إلى كلمات إلى جمل ----------------------
def alignment_to_words(alignment: dict):
    chars = alignment["characters"]
    starts = alignment["character_start_times_seconds"]
    ends = alignment["character_end_times_seconds"]

    words, cur, w_start, w_end = [], "", None, None
    for ch, s, e in zip(chars, starts, ends):
        if ch.isspace():
            if cur:
                words.append((cur, w_start, w_end))
                cur, w_start = "", None
            continue
        if not cur:
            w_start = s
        cur += ch
        w_end = e
    if cur:
        words.append((cur, w_start, w_end))
    return words


def words_to_cues(words):
    cues, buf, c_start = [], [], None
    for text, s, e in words:
        if not buf:
            c_start = s
        candidate = " ".join(buf + [text])
        too_long = len(candidate) > SUB_MAX_CHARS or (e - c_start) > SUB_MAX_DURATION
        if too_long and buf:
            cues.append((c_start, buf_end, " ".join(buf)))
            buf, c_start = [], s
        buf.append(text)
        buf_end = e
        if text.endswith((".", "?", "!", "…")):  # نهاية جملة
            cues.append((c_start, buf_end, " ".join(buf)))
            buf = []
    if buf:
        cues.append((c_start, buf_end, " ".join(buf)))
    return cues


def fmt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(cues, path: str):
    with open(path, "w", encoding="utf-8") as f:
        for i, (s, e, text) in enumerate(cues, 1):
            nxt = cues[i][0] if i < len(cues) else e + 1
            e = max(e, min(s + 1.0, nxt))  # لا تقل المدة عن ثانية إن أمكن
            wrapped = textwrap.fill(text, width=SUB_LINE_WIDTH)
            f.write(f"{i}\n{fmt_time(s)} --> {fmt_time(e)}\n{wrapped}\n\n")
    print(f"[OK] Saved subtitles -> {path} ({len(cues)} cues)")


# ---------------------- 3) حرق الترجمة (بدون ImageMagick) ----------------------
def make_subtitle_clip(text: str, start: float, end: float) -> ImageClip:
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    box_h = 220
    img = Image.new("RGBA", (W, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.multiline_text(
        (W // 2, 10), textwrap.fill(text, width=SUB_LINE_WIDTH), font=font,
        fill="white", stroke_width=3, stroke_fill="black",
        anchor="ma", align="center", spacing=10,
    )
    clip = ImageClip(np.array(img), transparent=True)
    return (clip.set_start(start).set_duration(end - start)
                .set_position(("center", H - box_h - SUB_BOTTOM_MARGIN + 120)))


# ---------------------- 4) الفيديو ----------------------
def make_scene(path: str, duration: float) -> CompositeVideoClip:
    clip = ImageClip(path)
    scale = max(W / clip.w, H / clip.h)
    clip = clip.resize(scale).set_duration(duration)
    clip = clip.resize(lambda t: 1 + ZOOM * t / duration)
    return CompositeVideoClip([clip.set_position("center")], size=(W, H)).set_duration(duration)


def build_video(audio_path: str, out_path: str, cues=None):
    voice = AudioFileClip(audio_path)
    total = voice.duration
    print(f"[INFO] Voice duration: {total:.1f}s")

    images = sorted(
        glob.glob(os.path.join(IMAGES_DIR, "*.jpg"))
        + glob.glob(os.path.join(IMAGES_DIR, "*.jpeg"))
        + glob.glob(os.path.join(IMAGES_DIR, "*.png"))
    )
    if not images:
        raise RuntimeError(f"No images found in '{IMAGES_DIR}'")
    random.shuffle(images)

    scenes, elapsed, i = [], 0.0, 0
    while elapsed < total:
        d = min(random.uniform(SCENE_MIN, SCENE_MAX), total - elapsed)
        scenes.append(make_scene(images[i % len(images)], d))
        elapsed += d
        i += 1
    print(f"[INFO] Scenes: {len(scenes)}")

    video = concatenate_videoclips(scenes, method="compose")

    # حرق الترجمة (اختياري)
    if BURN_SUBTITLES and cues:
        subs = [make_subtitle_clip(t, s, min(e + 0.1, total)) for s, e, t in cues]
        video = CompositeVideoClip([video] + subs, size=(W, H))

    if AMBIENT_FILE and os.path.exists(AMBIENT_FILE):
        amb = AudioFileClip(AMBIENT_FILE)
        amb = afx.audio_loop(amb, duration=total).volumex(AMBIENT_VOLUME)
        audio = CompositeAudioClip([voice, amb])
    else:
        audio = voice

    video = video.set_audio(audio).set_duration(total)
    video.write_videofile(out_path, fps=FPS, codec="libx264", audio_codec="aac")
    print(f"[OK] Video saved -> {out_path}")


if __name__ == "__main__":
    with open(SCRIPT_FILE, "r", encoding="utf-8") as f:
        script_text = f.read().strip()

    alignment = generate_voice_with_timestamps(script_text, OUTPUT_AUDIO)
    cues = words_to_cues(alignment_to_words(alignment))
    write_srt(cues, OUTPUT_SRT)
    build_video(OUTPUT_AUDIO, OUTPUT_VIDEO, cues)
