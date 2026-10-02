import base64, io, json, os, re, shutil, subprocess, time, wave, zipfile
from pathlib import Path

import requests
import streamlit as st
from PIL import Image, ImageDraw

# ============ الإعدادات ============
API = "https://openrouter.ai/api/v1/chat/completions"
TEXT_MODEL = "google/gemini-2.5-flash"
IMAGE_MODEL = "google/gemini-2.5-flash-image"
AUDIO_MODEL = "openai/gpt-audio-mini"
VOICES = ["ash", "onyx", "echo", "sage", "verse", "alloy", "ballad", "coral", "shimmer"]
FPS, W, H = 25, 1920, 1080
PCM_RATE = 24000  # gpt-audio pcm16: 24kHz mono

st.set_page_config(page_title="مولّد فيديوهات الغموض", page_icon="🎬", layout="wide")
st.markdown("<style>.main{direction:rtl;text-align:right}</style>", unsafe_allow_html=True)


# ============ أدوات مساعدة ============
def ffmpeg_bin():
    p = shutil.which("ffmpeg")
    if p:
        return p
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def headers(key):
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
            "X-Title": "Mystery Video Tool"}


def retry(fn, tries=3, wait=3):
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa
            last = e
            time.sleep(wait * (i + 1))
    raise last


# ============ 1) السيناريو ============
def generate_script(key, topic, minutes, scenes_n):
    words_total = int(minutes * 140)
    per_scene = words_total // scenes_n
    sys = (
        "You are a top YouTube scriptwriter for mystery, true-crime and mind-blowing-facts channels. "
        "Write gripping storytelling with a strong hook in the first scene, rising tension, and a "
        "surprising ending with a call to subscribe. Keep content factual or clearly presented as "
        "legend/theory; no graphic gore, no defamation of real private individuals. "
        "Return ONLY valid JSON, no markdown."
    )
    user = f"""Topic: {topic or 'choose a fascinating little-known mystery'}
Write the narration in Modern Standard Arabic (فصحى), cinematic documentary tone, fully diacritic-free.
Create exactly {scenes_n} scenes, about {per_scene} Arabic words of narration per scene.
JSON schema:
{{"title": "catchy Arabic YouTube title",
 "description": "Arabic YouTube description with hashtags",
 "tags": ["..."],
 "visual_style": "one English sentence describing a consistent cinematic look (palette, lighting, lens, era) for all images",
 "scenes": [{{"narration": "Arabic text", "image_prompt": "detailed English prompt for a cinematic 16:9 still, no text, no watermark, no real celebrities"}}]}}"""
    payload = {"model": TEXT_MODEL, "temperature": 0.9,
               "response_format": {"type": "json_object"},
               "messages": [{"role": "system", "content": sys}, {"role": "user", "content": user}]}

    def call():
        r = requests.post(API, headers=headers(key), json=payload, timeout=180)
        r.raise_for_status()
        txt = r.json()["choices"][0]["message"]["content"]
        txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
        data = json.loads(txt)
        assert data["scenes"], "no scenes"
        return data

    return retry(call)


# ============ 2) الصور ============
def placeholder(path):
    img = Image.new("RGB", (2880, 1620), (8, 8, 14))
    d = ImageDraw.Draw(img)
    for i in range(0, 1620, 6):
        c = 8 + int(30 * i / 1620)
        d.line([(0, i), (2880, i)], fill=(c, c, c + 8))
    img.save(path, quality=95)


def save_fit(raw, path):
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    w, h = img.size
    target = 16 / 9
    if w / h > target:
        nw = int(h * target); x = (w - nw) // 2; img = img.crop((x, 0, x + nw, h))
    else:
        nh = int(w / target); y = (h - nh) // 2; img = img.crop((0, y, w, y + nh))
    img.resize((2880, 1620), Image.LANCZOS).save(path, quality=95)


def generate_image(key, prompt, style, path):
    full = (f"Generate a photorealistic cinematic still, 16:9 widescreen. Style: {style}. "
            f"Scene: {prompt}. Moody, mysterious, dramatic lighting, no text, no letters, no watermark.")
    payload = {"model": IMAGE_MODEL, "modalities": ["image", "text"],
               "image_config": {"aspect_ratio": "16:9"},
               "messages": [{"role": "user", "content": full}]}

    def call():
        r = requests.post(API, headers=headers(key), json=payload, timeout=180)
        r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
        imgs = msg.get("images") or []
        if not imgs:
            raise RuntimeError("no image returned")
        url = imgs[0]["image_url"]["url"]
        save_fit(base64.b64decode(url.split(",", 1)[1]), path)

    try:
        retry(call, tries=3)
        return True
    except Exception:
        placeholder(path)
        return False


# ============ 3) الصوت ============
def generate_voice(key, text, voice, wav_path):
    payload = {
        "model": AUDIO_MODEL, "stream": True,
        "modalities": ["text", "audio"],
        "audio": {"voice": voice, "format": "pcm16"},
        "messages": [
            {"role": "system", "content":
                "You are a professional Arabic voice-over narrator. Read the user's text EXACTLY as written, "
                "in clear Modern Standard Arabic (فصحى), deep cinematic documentary tone, slow suspenseful "
                "pacing. Do not add, translate, or comment on anything."},
            {"role": "user", "content": text}],
    }

    def call():
        pcm = bytearray()
        with requests.post(API, headers=headers(key), json=payload, stream=True, timeout=300) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                line = line.decode("utf-8", "ignore")
                if not line.startswith("data:"):
                    continue
                d = line[5:].strip()
                if d == "[DONE]":
                    break
                obj = json.loads(d)
                if not obj.get("choices"):
                    continue
                a = (obj["choices"][0].get("delta") or {}).get("audio") or {}
                if a.get("data"):
                    pcm.extend(base64.b64decode(a["data"]))
        if len(pcm) < PCM_RATE:  # أقل من ثانية = فشل
            raise RuntimeError("empty audio")
        with wave.open(str(wav_path), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(PCM_RATE)
            w.writeframes(bytes(pcm))

    retry(call, tries=3)
    with wave.open(str(wav_path)) as w:
        return w.getnframes() / w.getframerate()


# ============ 4) المونتاج ============
def build_scene(ff, img, wav, dur, idx, out):
    total = dur + 0.6
    d = max(int(total * FPS), 2)
    mode = idx % 4
    base = f"zoompan=d={d}:s={W}x{H}:fps={FPS}"
    if mode == 0:    # zoom in
        z = f"{base}:z='1+0.22*on/{d}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2'"
    elif mode == 1:  # zoom out
        z = f"{base}:z='1.22-0.22*on/{d}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2'"
    elif mode == 2:  # pan left -> right
        z = f"{base}:z=1.18:x='(iw-iw/zoom)*on/{d}':y='ih/2-ih/zoom/2'"
    else:            # pan right -> left
        z = f"{base}:z=1.18:x='(iw-iw/zoom)*(1-on/{d})':y='ih/2-ih/zoom/2'"
    vf = f"{z},fade=t=in:st=0:d=0.4,fade=t=out:st={total-0.4:.2f}:d=0.4,format=yuv420p"
    cmd = [ff, "-y", "-i", str(img), "-i", str(wav), "-vf", vf, "-af", "apad",
           "-t", f"{total:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2", str(out)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-800:])


def concat(ff, clips, out, listfile):
    listfile.write_text("".join(f"file '{c.resolve().as_posix()}'\n" for c in clips))
    cmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
           "-c", "copy", "-movflags", "+faststart", str(out)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-800:])


def make_zip(folder, zpath):
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in folder.rglob("*"):
            if not f.is_file() or f == zpath or f.name == "list.txt" or "clips" in f.parts:
                continue
            z.write(f, f.relative_to(folder))


# ============ خط الإنتاج ============
def run_pipeline(key, topic, minutes, voice):
    ff = ffmpeg_bin()
    root = Path("output") / time.strftime("%Y%m%d_%H%M%S")
    (root / "images").mkdir(parents=True); (root / "audio").mkdir(); (root / "clips").mkdir()
    n = max(6, int(minutes * 3))
    bar, status = st.progress(0.0), st.empty()

    status.info("✍️ جاري كتابة السيناريو...")
    script = generate_script(key, topic, minutes, n)
    scenes = script["scenes"]
    n = len(scenes)
    (root / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "metadata.txt").write_text(
        f"{script.get('title','')}\n\n{script.get('description','')}\n\n{', '.join(script.get('tags', []))}",
        encoding="utf-8")
    st.session_state["title"] = script.get("title", "")

    clips, failed = [], 0
    for i, sc in enumerate(scenes):
        base = 0.05 + 0.85 * i / n
        status.info(f"🎨 المشهد {i+1}/{n}: الصورة...")
        bar.progress(base)
        img = root / "images" / f"scene_{i+1:02d}.jpg"
        if not generate_image(key, sc["image_prompt"], script.get("visual_style", ""), img):
            failed += 1

        status.info(f"🎙️ المشهد {i+1}/{n}: التعليق الصوتي...")
        wav = root / "audio" / f"scene_{i+1:02d}.wav"
        dur = generate_voice(key, sc["narration"], voice, wav)

        status.info(f"🎞️ المشهد {i+1}/{n}: المونتاج...")
        clip = root / "clips" / f"scene_{i+1:02d}.mp4"
        build_scene(ff, img, wav, dur, i, clip)
        clips.append(clip)

    status.info("🔗 جاري دمج المشاهد في الفيديو النهائي...")
    bar.progress(0.95)
    final = root / "final_video_16x9.mp4"
    concat(ff, clips, final, root / "list.txt")
    zpath = root / "project_export.zip"
    make_zip(root, zpath)
    bar.progress(1.0)
    status.success(f"✅ تم! ({n} مشهد" + (f"، {failed} صورة بديلة" if failed else "") + ")")
    return final, zpath


# ============ الواجهة ============
st.title("🎬 الأداة الأولى: مولّد فيديوهات الغموض (16:9)")
with st.sidebar:
    key = st.text_input("OpenRouter API Key", type="password",
                        value=os.getenv("OPENROUTER_API_KEY", ""))
    minutes = st.slider("مدة الفيديو (دقائق)", 3.0, 5.0, 4.0, 0.5)
    voice = st.selectbox("صوت الراوي", VOICES)

topic = st.text_area("موضوع القصة (اتركه فارغاً لاختيار تلقائي)",
                     placeholder="مثال: اختفاء الرحلة MH370 / لغز سفينة ماري سيليست")

if st.button("🚀 ابدأ الإنتاج", type="primary", disabled=not key):
    try:
        f, z = run_pipeline(key, topic, minutes, voice)
        st.session_state["result"] = (str(f), str(z))
    except Exception as e:
        st.error(f"فشل التنفيذ: {e}")

if "result" in st.session_state:
    f, z = map(Path, st.session_state["result"])
    if f.exists():
        if st.session_state.get("title"):
            st.subheader(st.session_state["title"])
        st.video(str(f))
        c1, c2 = st.columns(2)
        c1.download_button("⬇️ تحميل الفيديو MP4", f.read_bytes(), "final_video_16x9.mp4", "video/mp4")
        c2.download_button("📦 تحميل المشروع ZIP", z.read_bytes(), "project_export.zip", "application/zip")
