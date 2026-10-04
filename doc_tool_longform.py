# -*- coding: utf-8 -*-
"""
الأداة الأولى: مولّد الفيديو الوثائقي الطويل (Long-form 16:9)
------------------------------------------------------------
- يستقبل تسجيلك الصوتي ويحدد مدة الفيديو منه
- مشاهد 1920x1080 تتغير كل 3–5 ثوانٍ (Ken Burns للصور + قص عشوائي للفيديوهات)
- بدون موسيقى؛ طبقة مؤثرات بيئية خفيفة تحت الصوت (ملفاتك أو رياح مولَّدة تلقائياً)
- ملف .srt متزامن (Whisper للدقة، أو توزيع تناسبي من النص كبديل)

التشغيل:
    pip install streamlit "moviepy>=2.0" pillow numpy faster-whisper
    (وتأكد من تثبيت ffmpeg على النظام)
    streamlit run doc_tool_longform.py
"""
import math
import random
import tempfile
import wave
from pathlib import Path

import numpy as np
import streamlit as st
from PIL import Image
from moviepy import (
    AudioFileClip,
    CompositeAudioClip,
    VideoClip,
    VideoFileClip,
    afx,
    concatenate_audioclips,
    concatenate_videoclips,
    vfx,
)

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm"}
OUT_DIR = Path("output")
OUT_DIR.mkdir(exist_ok=True)


# ───────────────────────── 1) تخطيط المشاهد ─────────────────────────
def plan_scenes(total: float, lo: float = 3.0, hi: float = 5.0, seed=None):
    """يقسّم المدة الكلية إلى مشاهد طول كل منها بين lo و hi ثانية."""
    rng = random.Random(seed)
    durs, rem = [], total
    while rem > hi:
        d = rng.uniform(lo, hi)
        if rem - d < lo:  # تجنّب مشهد أخير قصير جداً
            d = rem / 2
        durs.append(d)
        rem -= d
    durs.append(rem)
    return durs


def assign_media(media: list, n: int, seed=None):
    """توزيع الوسائط على المشاهد دون تكرار متتالٍ."""
    rng = random.Random(seed)
    seq, pool, last = [], [], None
    while len(seq) < n:
        if not pool:
            pool = media[:]
            rng.shuffle(pool)
            if len(pool) > 1 and pool[0] == last:
                pool.append(pool.pop(0))
        last = pool.pop(0)
        seq.append(last)
    return seq


# ───────────────────────── 2) بناء المشاهد ─────────────────────────
def image_scene(path: str, dur: float, size, rng: random.Random):
    """صورة مع حركة Ken Burns (تقريب/تبعيد + إزاحة خفيفة) بدقة سينمائية."""
    W, H = size
    img = Image.open(path).convert("RGB")
    img.thumbnail((3200, 3200), Image.LANCZOS)
    iw, ih = img.size
    # أكبر مستطيل 16:9 داخل الصورة
    rw = min(iw, ih * W / H)
    rh = rw * H / W
    zoom_in = rng.random() < 0.5
    z0, z1 = (1.0, 1.12) if zoom_in else (1.12, 1.0)
    sx = (iw - rw) / 2
    sy = (ih - rh) / 2
    cx0, cy0 = iw / 2, ih / 2
    cx1 = iw / 2 + rng.uniform(-1, 1) * sx * 0.8
    cy1 = ih / 2 + rng.uniform(-1, 1) * sy * 0.8

    def make_frame(t):
        p = min(max(t / max(dur, 1e-6), 0), 1)
        p = p * p * (3 - 2 * p)  # easing ناعم
        z = z0 + (z1 - z0) * p
        w, h = rw / z, rh / z
        cx = cx0 + (cx1 - cx0) * p
        cy = cy0 + (cy1 - cy0) * p
        x = min(max(cx - w / 2, 0), iw - w)
        y = min(max(cy - h / 2, 0), ih - h)
        return np.asarray(img.resize((W, H), Image.BILINEAR, box=(x, y, x + w, y + h)))

    return VideoClip(make_frame, duration=dur)


def video_scene(path: str, dur: float, size, rng: random.Random):
    """مقطع فيديو: يُقتطع من نقطة عشوائية (أو يُكرَّر إن كان أقصر) ثم Fill-Crop إلى 16:9."""
    W, H = size
    clip = VideoFileClip(path, audio=False)
    if clip.duration < dur:
        clip = clip.with_effects([vfx.Loop(duration=dur)])
    else:
        start = rng.uniform(0, clip.duration - dur)
        clip = clip.subclipped(start, start + dur)
    s = max(W / clip.w, H / clip.h) * 1.001
    clip = clip.resized(s)
    clip = clip.cropped(x_center=clip.w / 2, y_center=clip.h / 2, width=W, height=H)
    return clip.with_duration(dur)


def build_video(durs, media_seq, size, seed):
    rng = random.Random(seed)
    clips = []
    for d, m in zip(durs, media_seq):
        ext = Path(m).suffix.lower()
        clips.append(video_scene(m, d, size, rng) if ext in VIDEO_EXT else image_scene(m, d, size, rng))
    return concatenate_videoclips(clips, method="chain")


# ───────────────────────── 3) المؤثرات البيئية ─────────────────────────
def synth_wind(path: str, seconds: int = 60, sr: int = 44100, seed: int = 0):
    """رياح هادئة مولّدة (ضوضاء وردية + تموّج بطيء) تُكرَّر لاحقاً. بديل إن لم ترفع مؤثراتك."""
    rng = np.random.default_rng(seed)
    n = seconds * sr
    chans = []
    for _ in range(2):
        spec = np.fft.rfft(rng.standard_normal(n))
        f = np.fft.rfftfreq(n, 1 / sr)
        f[0] = 1
        spec = spec / np.sqrt(f)
        spec[f > 2500] *= 0.05  # قصّ الترددات العالية = صوت أدفأ
        x = np.fft.irfft(spec, n)
        t = np.arange(n) / sr
        swell = 0.65 + 0.35 * np.sin(2 * np.pi * t / 11.0 + rng.uniform(0, 6.28))
        x = x * swell
        chans.append(x / (np.max(np.abs(x)) + 1e-9))
    data = (np.stack(chans, axis=1) * 0.8 * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data.tobytes())


def build_ambient(files, total, level, tmpdir, seed):
    if files:
        rng = random.Random(seed)
        files = files[:]
        rng.shuffle(files)
        base = concatenate_audioclips([AudioFileClip(f) for f in files])
    else:
        wav = str(Path(tmpdir) / "wind.wav")
        synth_wind(wav, seed=seed)
        base = AudioFileClip(wav)
    fade = min(3.0, total / 4)
    return base.with_effects(
        [
            afx.AudioLoop(duration=total),
            afx.MultiplyVolume(level),
            afx.AudioFadeIn(fade),
            afx.AudioFadeOut(fade),
        ]
    )


# ───────────────────────── 4) ملف الترجمة SRT ─────────────────────────
def fmt_ts(t: float) -> str:
    t = max(t, 0)
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def group_words(words, max_words=7, max_chars=70, max_dur=5.0):
    """يجمّع الكلمات المؤقّتة في أسطر ترجمة مريحة للقراءة."""
    cues, cur = [], []
    for w in words:
        cur.append(w)
        text = " ".join(x["word"] for x in cur)
        dur = cur[-1]["end"] - cur[0]["start"]
        end_punct = w["word"].rstrip().endswith((".", "؟", "?", "!", "،", ",", "…", "؛"))
        if len(cur) >= max_words or len(text) >= max_chars or dur >= max_dur or (end_punct and len(cur) >= 3):
            cues.append(cur)
            cur = []
    if cur:
        cues.append(cur)
    return [(c[0]["start"], c[-1]["end"], " ".join(x["word"] for x in c).strip()) for c in cues]


def srt_from_whisper(audio_path, model_size, language):
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device="auto", compute_type="auto")
    segments, _ = model.transcribe(
        audio_path, language=language or None, word_timestamps=True, vad_filter=True
    )
    words = []
    for seg in segments:
        for w in seg.words or []:
            words.append({"word": w.word.strip(), "start": w.start, "end": w.end})
    return group_words(words)


def srt_from_script(script: str, total: float, max_chars=70):
    """بديل بلا Whisper: توزيع النص على المدة الكلية بنسبة عدد الحروف (أقل دقة)."""
    import re

    parts = [p.strip() for p in re.split(r"(?<=[\.\!\?؟…])\s+|\n+", script) if p.strip()]
    lines = []
    for p in parts:
        while len(p) > max_chars:
            cut = p.rfind(" ", 0, max_chars)
            cut = cut if cut > 20 else max_chars
            lines.append(p[:cut].strip())
            p = p[cut:].strip()
        lines.append(p)
    weights = [max(len(l), 1) for l in lines]
    tot_w = sum(weights)
    cues, t = [], 0.0
    for l, w in zip(lines, weights):
        d = total * w / tot_w
        cues.append((t, t + d, l))
        t += d
    return cues


def write_srt(cues, path):
    with open(path, "w", encoding="utf-8") as f:
        for i, (a, b, text) in enumerate(cues, 1):
            f.write(f"{i}\n{fmt_ts(a)} --> {fmt_ts(b)}\n{text}\n\n")


# ───────────────────────── 5) واجهة Streamlit ─────────────────────────
def save_uploads(files, folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, f in enumerate(files):
        p = folder / f"{i:03}_{Path(f.name).name}"
        p.write_bytes(f.getbuffer())
        paths.append(str(p))
    return paths


def main():
    st.set_page_config(page_title="أداة الفيديو الوثائقي الطويل", page_icon="🎬", layout="wide")
    st.title("🎬 الأداة الأولى — فيديو وثائقي طويل (16:9)")

    with st.sidebar:
        st.header("الإعدادات")
        draft = st.toggle("مسودة سريعة (1280×720)", value=False)
        lo, hi = st.slider("مدة المشهد (ثوانٍ)", 3.0, 5.0, (3.0, 5.0), 0.5)
        fps = st.selectbox("FPS", [24, 25, 30], index=0)
        level = st.slider("مستوى المؤثرات البيئية", 0.02, 0.25, 0.08, 0.01)
        preset = st.selectbox("سرعة الترميز", ["medium", "fast", "slow", "veryfast"], index=0)
        loudnorm = st.checkbox("توحيد مستوى الصوت (-16 LUFS) لليوتيوب", value=True)
        seed = st.number_input("Seed (لتكرار نفس الترتيب)", 0, 10**6, 7)
        st.divider()
        st.subheader("الترجمة")
        sub_mode = st.radio("طريقة الترجمة", ["Whisper (دقيقة)", "من النص (تقريبية)", "بدون"])
        whisper_size = st.selectbox("حجم نموذج Whisper", ["small", "medium", "large-v3", "base"], index=0)
        lang = st.text_input("رمز اللغة", "ar")

    c1, c2 = st.columns(2)
    with c1:
        voice_up = st.file_uploader("🎙️ التعليق الصوتي", type=["wav", "mp3", "m4a", "aac", "flac", "ogg"])
        sfx_up = st.file_uploader(
            "🌊 مؤثرات بيئية (اختياري — إن تُرك فارغاً تُولَّد رياح هادئة)",
            type=["wav", "mp3", "ogg", "m4a"],
            accept_multiple_files=True,
        )
    with c2:
        media_up = st.file_uploader(
            "🖼️ الصور / مقاطع الفيديو البصرية",
            type=[e.strip(".") for e in IMAGE_EXT | VIDEO_EXT],
            accept_multiple_files=True,
        )
        script = ""
        if sub_mode == "من النص (تقريبية)":
            script = st.text_area("نص التعليق (للترجمة)", height=160)

    ready = voice_up and media_up and (sub_mode != "من النص (تقريبية)" or script.strip())
    if not st.button("🚀 توليد الفيديو", type="primary", disabled=not ready):
        return

    size = (1280, 720) if draft else (1920, 1080)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        voice_path = save_uploads([voice_up], tmp / "voice")[0]
        media = save_uploads(media_up, tmp / "media")
        sfx = save_uploads(sfx_up, tmp / "sfx") if sfx_up else []

        voice = AudioFileClip(voice_path)
        total = voice.duration
        durs = plan_scenes(total, lo, hi, seed)
        seq = assign_media(media, len(durs), seed)
        st.info(f"مدة الصوت {total:.1f}ث → {len(durs)} مشهداً (متوسط {total/len(durs):.1f}ث)")

        stem = Path(voice_up.name).stem
        out_mp4 = OUT_DIR / f"{stem}_16x9.mp4"
        out_srt = OUT_DIR / f"{stem}.srt"

        # الترجمة
        if sub_mode != "بدون":
            with st.status("جارٍ إنشاء ملف الترجمة…", expanded=False) as s:
                try:
                    if sub_mode.startswith("Whisper"):
                        cues = srt_from_whisper(voice_path, whisper_size, lang)
                    else:
                        cues = srt_from_script(script, total)
                    write_srt(cues, str(out_srt))
                    s.update(label=f"تم إنشاء الترجمة ({len(cues)} سطر)", state="complete")
                except Exception as e:  # noqa
                    s.update(label=f"فشل إنشاء الترجمة: {e}", state="error")

        # الفيديو والصوت
        with st.status("جارٍ المونتاج والتصدير… (قد يستغرق وقتاً)", expanded=True) as s:
            video = build_video(durs, seq, size, seed)
            ambient = build_ambient(sfx, total, level, str(tmp), seed)
            mix = CompositeAudioClip([ambient, voice]).with_duration(total)
            final = video.with_audio(mix).with_duration(total)
            params = ["-pix_fmt", "yuv420p", "-movflags", "+faststart"]
            if loudnorm:
                params += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
            final.write_videofile(
                str(out_mp4),
                fps=fps,
                codec="libx264",
                audio_codec="aac",
                audio_bitrate="192k",
                bitrate="12M" if not draft else "4M",
                preset=preset,
                threads=4,
                ffmpeg_params=params,
                logger=None,
            )
            s.update(label="اكتمل التصدير ✅", state="complete")

    st.success("جاهز!")
    st.video(str(out_mp4))
    d1, d2 = st.columns(2)
    d1.download_button("⬇️ تحميل الفيديو", out_mp4.read_bytes(), file_name=out_mp4.name, mime="video/mp4")
    if out_srt.exists():
        d2.download_button("⬇️ تحميل SRT", out_srt.read_bytes(), file_name=out_srt.name, mime="application/x-subrip")


if __name__ == "__main__":
    main()
