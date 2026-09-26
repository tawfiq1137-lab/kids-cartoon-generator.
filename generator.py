"""
generator.py
------------
الوحدة المسؤولة عن كل خطوات توليد حزمة قصة الأطفال باستخدام مكتبة
google-genai الجديدة:

    1. generate_script  -> كتابة السيناريو (نص) عبر Gemini.
    2. generate_images  -> رسم صورة لكل مشهد عبر Gemini (gemini-2.5-flash-image).
    3. generate_audios  -> تسجيل تعليق صوتي لكل مشهد عبر Gemini TTS.
    4. create_zip_package -> تجميع كل الملفات (نص + صور + صوت) في حزمة ZIP واحدة.
"""

import json
import os
import re
import wave
import zipfile
from typing import Dict, List

from google import genai
from google.genai import types

# --------------------------------------------------------------------------
# أسماء النماذج
# --------------------------------------------------------------------------
TEXT_MODEL = "gemini-2.5-flash"
IMAGE_MODEL = "gemini-2.5-flash-image"
TTS_MODEL = "gemini-2.5-flash-preview-tts"
TTS_VOICE = "Kore"

# --------------------------------------------------------------------------
# 1) توليد السيناريو (النص)
# --------------------------------------------------------------------------
SYSTEM_INSTRUCTION = """
أنت كاتب قصص أطفال محترف. مهمتك هي كتابة قصة قصيرة وممتعة ومناسبة للأطفال
بناءً على الفكرة التي يقدمها المستخدم.

يجب أن يكون ردك حصراً على شكل JSON صالح (valid JSON) بدون أي نص إضافي قبله
أو بعده، وبدون أي شرح، وبالتنسيق التالي بالضبط:

{
  "title": "عنوان القصة",
  "scenes": [
    {
      "scene_number": 1,
      "narration": "نص السرد الخاص بهذا المشهد",
      "image_prompt": "وصف تفصيلي بالإنجليزية للصورة المناسبة لهذا المشهد"
    }
  ]
}

قواعد إلزامية:
- لا تضف علامات ماركداون مثل ```json أو ``` حول الرد.
- لا تضف أي تعليق أو مقدمة أو خاتمة خارج كائن JSON.
- اجعل عدد المشاهد بين 4 و 8 مشاهد.
- اجعل السرد (narration) باللغة العربية الفصحى المبسطة المناسبة للأطفال.
- اجعل image_prompt وصفاً بصرياً بالإنجليزية يصلح لاستخدامه في نموذج توليد صور،
  مع الإشارة دوماً إلى أسلوب رسم "children's book illustration, colorful, cartoon style".
- تأكد أن الناتج قابل للتحويل مباشرة عبر json.loads بدون أي أخطاء.
"""


def _clean_json_text(text: str) -> str:
    """تنظيف النص المرتجع من النموذج من أي حشو ماركداون قبل json.loads."""
    cleaned = (text or "").strip()

    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    if not (cleaned.startswith("{") and cleaned.endswith("}")):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start:end + 1]

    return cleaned


def generate_script(prompt: str, api_key: str) -> dict:
    """
    يولّد سيناريو قصة أطفال باستخدام Gemini، ويعيد النتيجة كـ dict:
    {"title": "...", "scenes": [{"scene_number", "narration", "image_prompt"}, ...]}
    """
    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model=TEXT_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            temperature=0.9,
        ),
    )

    cleaned_text = _clean_json_text(response.text)

    try:
        result = json.loads(cleaned_text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"فشل تحليل استجابة النموذج كـ JSON صالح.\n"
            f"الخطأ: {e}\n"
            f"النص المستلم (بعد التنظيف): {cleaned_text[:500]}"
        ) from e

    if "title" not in result or "scenes" not in result:
        raise ValueError(
            f"استجابة النموذج لا تحتوي على الحقول المطلوبة (title, scenes): {result}"
        )

    return result


# --------------------------------------------------------------------------
# 2) توليد الصور
# --------------------------------------------------------------------------
def generate_images(scenes: List[dict], output_dir: str, api_key: str) -> Dict[int, str]:
    """
    يولّد صورة واحدة لكل مشهد باستخدام gemini-2.5-flash-image.

    Returns:
        dict بالشكل {scene_number: مسار ملف الصورة}
    """
    os.makedirs(output_dir, exist_ok=True)
    client = genai.Client(api_key=api_key)

    image_paths: Dict[int, str] = {}

    for scene in scenes:
        scene_number = scene.get("scene_number")
        image_prompt = scene.get("image_prompt", "").strip()

        if not image_prompt:
            continue

        try:
            response = client.models.generate_content(
                model=IMAGE_MODEL,
                contents=[image_prompt],
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                ),
            )

            saved = False
            for part in response.candidates[0].content.parts:
                if getattr(part, "inline_data", None) is not None:
                    file_path = os.path.join(output_dir, f"scene_{scene_number}.png")
                    with open(file_path, "wb") as f:
                        f.write(part.inline_data.data)
                    image_paths[scene_number] = file_path
                    saved = True
                    break

            if not saved:
                raise RuntimeError("لم يُرجع النموذج أي بيانات صورة لهذا المشهد.")

        except Exception as e:
            raise RuntimeError(
                f"فشل توليد صورة المشهد رقم {scene_number}: {e}"
            ) from e

    return image_paths


# --------------------------------------------------------------------------
# 3) توليد التعليق الصوتي
# --------------------------------------------------------------------------
def _save_wave_file(file_path: str, pcm_data: bytes, channels: int = 1,
                     rate: int = 24000, sample_width: int = 2) -> None:
    """حفظ بيانات PCM الخام كملف WAV صالح للتشغيل."""
    with wave.open(file_path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm_data)


def generate_audios(scenes: List[dict], output_dir: str, api_key: str) -> Dict[int, str]:
    """
    يولّد تعليقاً صوتياً واحداً لكل مشهد باستخدام Gemini TTS.

    Returns:
        dict بالشكل {scene_number: مسار ملف الصوت}
    """
    os.makedirs(output_dir, exist_ok=True)
    client = genai.Client(api_key=api_key)

    audio_paths: Dict[int, str] = {}

    for scene in scenes:
        scene_number = scene.get("scene_number")
        narration = scene.get("narration", "").strip()

        if not narration:
            continue

        try:
            response = client.models.generate_content(
                model=TTS_MODEL,
                contents=narration,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=TTS_VOICE,
                            )
                        )
                    ),
                ),
            )

            pcm_data = response.candidates[0].content.parts[0].inline_data.data
            file_path = os.path.join(output_dir, f"scene_{scene_number}.wav")
            _save_wave_file(file_path, pcm_data)
            audio_paths[scene_number] = file_path

        except Exception as e:
            raise RuntimeError(
                f"فشل توليد الصوت للمشهد رقم {scene_number}: {e}"
            ) from e

    return audio_paths


# --------------------------------------------------------------------------
# 4) تجميع الحزمة النهائية (ZIP)
# --------------------------------------------------------------------------
def _sanitize_filename(name: str) -> str:
    """تحويل عنوان القصة إلى اسم ملف آمن (بدون رموز خاصة)."""
    name = (name or "story").strip()
    name = re.sub(r"[^\w\u0600-\u06FF\- ]", "", name)  # يسمح بالعربية والإنجليزية والأرقام
    name = re.sub(r"\s+", "_", name)
    return name or "story"


def create_zip_package(script: dict, images_dir: str, audio_dir: str, output_dir: str) -> str:
    """
    يجمع سيناريو القصة (JSON) وكل الصور والملفات الصوتية في حزمة ZIP واحدة.

    Args:
        script: القاموس المُرجع من generate_script.
        images_dir: المجلد الذي يحتوي على صور المشاهد.
        audio_dir: المجلد الذي يحتوي على ملفات صوت المشاهد.
        output_dir: المجلد الذي سيوضع فيه ملف ZIP الناتج.

    Returns:
        المسار الكامل لملف ZIP الناتج.
    """
    os.makedirs(output_dir, exist_ok=True)

    safe_title = _sanitize_filename(script.get("title", "story"))
    zip_path = os.path.join(output_dir, f"{safe_title}.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. ملف السيناريو الكامل بصيغة JSON
        zf.writestr("story.json", json.dumps(script, ensure_ascii=False, indent=2))

        # 2. الصور
        if os.path.isdir(images_dir):
            for file_name in sorted(os.listdir(images_dir)):
                full_path = os.path.join(images_dir, file_name)
                if os.path.isfile(full_path):
                    zf.write(full_path, arcname=os.path.join("images", file_name))

        # 3. الملفات الصوتية
        if os.path.isdir(audio_dir):
            for file_name in sorted(os.listdir(audio_dir)):
                full_path = os.path.join(audio_dir, file_name)
                if os.path.isfile(full_path):
                    zf.write(full_path, arcname=os.path.join("audio", file_name))

    return zip_path
