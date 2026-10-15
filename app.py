"""
Tool 1 (Streamlit): English script -> ElevenLabs voice (fixed Voice ID) + timestamps
-> voiceover.mp3 + subtitles.srt -> 16:9 video from uploaded images. No background music.
"""

import base64
import glob
import os
import random
import tempfile
import textwrap

import numpy as np
import requests
import streamlit as st
from PIL import Image, ImageDraw, ImageFont, ImageOps

# 🛠️ حل مشكلة ANTIALIAS لضمان عمل MoviePy بسلاسة مع الإصدارات الحديثة
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

from moviepy.editor import (
    AudioFileClip, CompositeAudioClip, CompositeVideoClip, ImageClip,
    concatenate_videoclips,
)
import moviepy.audio.fx.all as afx

# ======================= إعدادات ثابتة =======================
MODEL_ID = "eleven_multilingual_v2"
VOICE_SETTINGS = {"stability": 0.60, "similarity_boost": 0.80, "style": 0.0}
MAX_CHARS_PER_REQUEST = 9500          # حد ElevenLabs للطلب الواحد تقريبًا 10,000 حرف
FPS = 24
SCENE_MIN, SCENE_MAX = 3.0, 5.0
ZOOM = 0.05
AMBIENT_VOLUME = 0.06

SUB_MAX_CHARS = 84
SUB_LINE_WIDTH = 42
SUB_MAX_DURATION = 7.0
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",   # Streamlit Cloud (via packages.txt)
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]

RESOLUTIONS = {
    "720p (أسرع، موصى به على Streamlit Cloud)": (1280, 720),
    "1080p (جودة أعلى، أبطأ وأثقل)": (1920, 1080),
}


def get_secret(name: str, default: str = "") -> str:
    try:
        return st.secrets.get(name, default)
    except Exception:
        return os.getenv(name, default)


# ---------------------- 1) الصوت + التوقيتات ----------------------
def generate_voice_with_timestamps(text, api_key, voice_id, mp3_path):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
    headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
    payload = {"text": text, "model_id": MODEL_ID, "voice_settings": VOICE_SETTINGS}

    r = requests.post(url, headers=headers, json=payload, timeout=600)
    if r.status_code != 200:
        raise RuntimeError(f"ElevenLabs error {r.status_code}: {r.text}")

    data = r.json()
    with open(mp3_path, "wb") as f:
        f.write(base64.b64decode(data["audio_base64"]))
    return data["alignment"]


def generate_voice_plain(text, api_key, voice_id, mp3_path):
    """TTS القياسي بدون توقيتات (يعمل على الحسابات المجانية)."""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {"xi-api-key": api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"}
    payload = {"text": text, "model_id": MODEL_ID, "voice_settings": VOICE_SETTINGS}

    r = requests.post(url, headers=headers, json=payload, timeout=600)
    if r.status_code != 200:
        raise RuntimeError(f"ElevenLabs error {r.status_code}: {r.text[:300]}")
    with open(mp3_path, "wb") as f:
        f.write(r.content)


def estimate_words(text, duration):
    """يوزّع مدة الصوت على الكلمات محليًا حسب طول الكلمة وعلامات الترقيم."""
    tokens = text.split()
    if not tokens:
        return []
    weights = []
    for w in tokens:
        wt = len(w.strip(".,;:!?…\"'()-")) + 1.0
        if w.endswith((".", "?", "!", "…")):
            wt += 6          # وقفة نهاية الجملة
        elif w.endswith((",", ";", ":")):
            wt += 3          # وقفة قصيرة
        weights.append(wt)

    total_w = sum(weights)
    words, t = [], 0.0
    for w, wt in zip(tokens, weights):
        d = duration * wt / total_w
        words.append((w, t, t + d))
        t += d
    return words


# ---------------------- 2) الحروف -> كلمات -> جمل -> SRT ----------------------
def alignment_to_words(alignment):
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
    cues, buf, c_start, buf_end = [], [], None, None
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
        if text.endswith((".", "?", "!", "…")):
            cues.append((c_start, buf_end, " ".join(buf)))
            buf = []
    if buf:
        cues.append((c_start, buf_end, " ".join(buf)))
    return cues


def fmt_time(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(cues, path):
    with open(path, "w", encoding="utf-8") as f:
        for i, (s, e, text) in enumerate(cues, 1):
            nxt = cues[i][0] if i < len(cues) else e + 1
            e = max(e, min(s + 1.0, nxt))
            wrapped = textwrap.fill(text, width=SUB_LINE_WIDTH)
            f.write(f"{i}\n{fmt_time(s)} --> {fmt_time(e)}\n{wrapped}\n\n")


# ---------------------- 3) الصور ----------------------
def prepare_images(uploaded_files, folder, W, H):
    """يحفظ الصور المرفوعة بحجم يغطي الإطار (يوفّر الذاكرة)."""
    paths = []
    for i, up in enumerate(uploaded_files):
        img = ImageOps.exif_transpose(Image.open(up)).convert("RGB")
        scale = max(W / img.width, H / img.height)
        new_size = (max(W, round(img.width * scale)), max(H, round(img.height * scale)))
        img = img.resize(new_size, Image.LANCZOS)
        p = os.path.join(folder, f"img_{i:03d}.jpg")
        img.save(p, quality=90)
        paths.append(p)
    return paths


# ---------------------- 4) الترجمة المحروقة (بدون ImageMagick) ----------------------
def load_font(size):
    for p in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def make_subtitle_clip(text, start, end, W, H):
    font_size = int(44 * W / 1920)
    font = load_font(font_size)
    box_h = int(220 * W / 1920)
    img = Image.new("RGBA", (W, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.multiline_text(
        (W // 2, 10), textwrap.fill(text, width=SUB_LINE_WIDTH), font=font,
        fill="white", stroke_width=max(2, font_size // 14), stroke_fill="black",
        anchor="ma", align="center", spacing=10,
    )
    clip = ImageClip(np.array(img), transparent=True)
    y = H - box_h - int(40 * W / 1920)
    return clip.set_start(start).set_duration(end - start).set_position(("center", y))


# ---------------------- 5) الفيديو ----------------------
def make_scene(path, duration, W, H):
    clip = ImageClip(path)
    scale = max(W / clip.w, H / clip.h)
    clip = clip.resize(scale).set_duration(duration)
    clip = clip.resize(lambda t: 1 + ZOOM * t / duration)
    return CompositeVideoClip([clip.set_position("center")], size=(W, H)).set_duration(duration)


def build_video(audio_path, image_paths, out_path, W, H, cues, burn, ambient_path, progress):
    voice = AudioFileClip(audio_path)
    total = voice.duration

    paths = image_paths[:]
    random.shuffle(paths)

    scenes, elapsed, i = [], 0.0, 0
    while elapsed < total:
        d = min(random.uniform(SCENE_MIN, SCENE_MAX), total - elapsed)
        scenes.append(make_scene(paths[i % len(paths)], d, W, H))
        elapsed += d
        i += 1
    progress(f"تم تجهيز {len(scenes)} مشهد، جارٍ الدمج والتصدير...")

    video = concatenate_videoclips(scenes, method="compose")

    if burn and cues:
        subs = [make_subtitle_clip(t, s, min(e + 0.1, total), W, H) for s, e, t in cues]
        video = CompositeVideoClip([video] + subs, size=(W, H))

    if ambient_path:
        amb = AudioFileClip(ambient_path)
        amb = afx.audio_loop(amb, duration=total).volumex(AMBIENT_VOLUME)
        audio = CompositeAudioClip([voice, amb])
    else:
        audio = voice

    video = video.set_audio(audio).set_duration(total)
    video.write_videofile(
        out_path, fps=FPS, codec="libx264", audio_codec="aac",
        preset="ultrafast", threads=2, logger=None,
    )
    voice.close()
    return total, len(scenes)


def run_pipeline(script, images, api_key, voice_id, resolution, burn, ambient_up, use_ts, status):
    W, H = resolution
    with tempfile.TemporaryDirectory() as tmp:
        mp3_path = os.path.join(tmp, "voiceover.mp3")
        srt_path = os.path.join(tmp, "subtitles.srt")
        mp4_path = os.path.join(tmp, "final.mp4")

        status.write("1/3 توليد الصوت من ElevenLabs...")
        words = None
        if use_ts:
            try:
                alignment = generate_voice_with_timestamps(script, api_key, voice_id, mp3_path)
                words = alignment_to_words(alignment)
            except Exception as e:
                status.write(f"⚠️ تعذّرت التوقيتات الدقيقة ({str(e)[:200]}). سيتم التقدير محليًا.")
        if words is None:
            generate_voice_plain(script, api_key, voice_id, mp3_path)
            probe = AudioFileClip(mp3_path)
            audio_duration = probe.duration
            probe.close()
            words = estimate_words(script, audio_duration)

        status.write("2/3 إنشاء ملف SRT...")
        cues = words_to_cues(words)
        write_srt(cues, srt_path)

        status.write("3/3 تجهيز الصور وبناء الفيديو (قد يستغرق عدة دقائق)...")
        img_paths = prepare_images(images, tmp, W, H)

        ambient_path = None
        if ambient_up is not None:
            ambient_path = os.path.join(tmp, "ambient" + os.path.splitext(ambient_up.name)[1])
            with open(ambient_path, "wb") as f:
                f.write(ambient_up.getbuffer())

        duration, n_scenes = build_video(
            mp3_path, img_paths, mp4_path, W, H, cues, burn, ambient_path, status.write
        )

        with open(mp4_path, "rb") as f:
            mp4_bytes = f.read()
        with open(mp3_path, "rb") as f:
            mp3_bytes = f.read()
        with open(srt_path, "rb") as f:
            srt_bytes = f.read()

    return {
        "mp4": mp4_bytes, "mp3": mp3_bytes, "srt": srt_bytes,
        "duration": duration, "scenes": n_scenes,
    }


# ============================ الواجهة ============================
st.set_page_config(page_title="Tool 1 - Video Maker", page_icon="🎬", layout="centered")
st.title("🎬 الأداة الأولى: فيديو طويل 16:9")
st.caption("سكربت إنجليزي → صوت ElevenLabs + ترجمة SRT → فيديو من صورك (بدون موسيقى)")

with st.sidebar:
    st.header("الإعدادات")
    api_key = get_secret("ELEVENLABS_API_KEY") or st.text_input("ElevenLabs API Key", type="password")
    voice_id = get_secret("VOICE_ID") or st.text_input("Voice ID (ثابت)")
    res_label = st.selectbox("الدقة", list(RESOLUTIONS.keys()))
    burn = st.checkbox("حرق الترجمة على الفيديو", value=False,
                       help="اتركها مغلقة إن أردت رفع SRT كترجمة CC في يوتيوب والحفاظ على مظهر سينمائي نظيف.")
    use_ts = st.checkbox("استخدام توقيتات ElevenLabs الدقيقة", value=False,
                         help="تتطلب صلاحية/خطة مدفوعة. المغلق = تقدير التوقيتات محليًا (يعمل مع الخطة المجانية). عند الفشل يتم التقدير تلقائيًا.")
    ambient_up = st.file_uploader("مؤثر طبيعي خفيف (اختياري)", type=["mp3", "wav"])

script = st.text_area("النص الإنجليزي (Script)", height=300,
                      placeholder="Paste your English script here...")
st.caption(f"عدد الأحرف: {len(script)} / {MAX_CHARS_PER_REQUEST}")

images = st.file_uploader("ارفع الصور (JPG/PNG بنسبة 16:9 يفضّل)",
                          type=["jpg", "jpeg", "png"], accept_multiple_files=True)
if images:
    st.caption(f"تم رفع {len(images)} صورة")

if st.button("🚀 توليد الفيديو", type="primary"):
    if not api_key or not voice_id:
        st.error("أدخل ElevenLabs API Key و Voice ID (في الشريط الجانبي أو عبر Secrets).")
    elif not script.strip():
        st.error("أدخل النص الإنجليزي أولًا.")
    elif len(script) > MAX_CHARS_PER_REQUEST:
        st.error(f"النص أطول من الحد ({MAX_CHARS_PER_REQUEST} حرف). قسّمه إلى جزأين.")
    elif not images:
        st.error("ارفع صورة واحدة على الأقل.")
    else:
        try:
            with st.status("جارٍ العمل...", expanded=True) as status:
                st.session_state["result"] = run_pipeline(
                    script.strip(), images, api_key, voice_id,
                    RESOLUTIONS[res_label], burn, ambient_up, use_ts, status,
                )
                status.update(label="اكتمل ✅", state="complete")
        except Exception as e:
            st.error(f"حدث خطأ: {e}")

res = st.session_state.get("result")
if res:
    st.success(f"المدة: {res['duration'] / 60:.1f} دقيقة | عدد المشاهد: {res['scenes']}")
    st.video(res["mp4"])
    c1, c2, c3 = st.columns(3)
    c1.download_button("⬇️ الفيديو (MP4)", res["mp4"], "final.mp4", "video/mp4")
    c2.download_button("⬇️ الترجمة (SRT)", res["srt"], "subtitles.srt", "text/plain")
    c3.download_button("⬇️ الصوت (MP3)", res["mp3"], "voiceover.mp3", "audio/mpeg")
