"""
generator.py
------------
الوحدة المسؤولة عن كل خطوات توليد حزمة قصة الأطفال، عبر OpenRouter
(https://openrouter.ai) بدل الاتصال المباشر بـ Google — لتفادي تعقيدات
الفوترة المباشرة مع Google Cloud لحسابات الأفراد في السعودية.

    1. generate_script  -> كتابة السيناريو (نص) عبر Gemini (chat/completions).
    2. generate_images  -> رسم صورة لكل مشهد عبر Gemini Image (images endpoint).
    3. generate_audios  -> تسجيل تعليق صوتي لكل مشهد عبر TTS (audio/speech endpoint).
    4. create_zip_package -> تجميع كل الملفات (نص + صور + صوت) في حزمة ZIP واحدة.

كل الدوال تحتاج مفتاح OpenRouter API (يبدأ بـ sk-or-v1-...) بدل مفتاح Gemini.
"""

import base64
import json
import os
import re
import time
import wave
import zipfile
from typing import Dict, List

import requests

# --------------------------------------------------------------------------
# إعدادات OpenRouter
# --------------------------------------------------------------------------
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

TEXT_MODEL = "google/gemini-2.5-flash"
IMAGE_MODEL = "google/gemini-2.5-flash-image"
TTS_MODEL = "openai/gpt-audio-mini"
TTS_VOICE = "alloy"
TTS_FORMAT = "pcm16"
PCM_SAMPLE_RATE = 24000  # التردد القياسي المستخدم في مخرجات صوت OpenAI

MAX_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 3
REQUEST_TIMEOUT_SECONDS = 120


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # اختياري لكن مفيد ليظهر مشروعك بشكل أوضح في لوحة OpenRouter
        "HTTP-Referer": "https://kids-cartoon-generator.streamlit.app",
        "X-Title": "Kids Cartoon Generator",
    }


def _post_with_retry(url: str, api_key: str, json_payload: dict = None,
                      expect_json: bool = True):
    """
    يرسل POST مع إعادة محاولة تلقائية عند 429 (تجاوز حصة/معدل) أو 5xx
    (مشاكل خوادم مؤقتة). يرجع naturally الاستجابة (Response) أو يرفع استثناء واضح.
    """
    last_error_message = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(
                url,
                headers=_headers(api_key),
                json=json_payload,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.exceptions.RequestException as e:
            last_error_message = f"فشل الاتصال بالشبكة: {e}"
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BASE_DELAY_SECONDS * attempt)
            continue

        if response.status_code == 200:
            return response

        # 401/403 = مفتاح خاطئ أو صلاحيات ناقصة، 402 = رصيد غير كافٍ
        if response.status_code in (401, 402, 403):
            raise RuntimeError(
                f"خطأ في المفتاح أو الرصيد ({response.status_code}): {response.text[:500]}"
            )

        # 404 = نموذج غير موجود
        if response.status_code == 404:
            raise RuntimeError(
                f"النموذج غير موجود على OpenRouter (404): {response.text[:500]}"
            )

        # 429 و 5xx تستحق إعادة المحاولة
        if response.status_code == 429 or response.status_code >= 500:
            last_error_message = f"{response.status_code}: {response.text[:500]}"
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BASE_DELAY_SECONDS * attempt)
            continue

        # أي خطأ آخر غير متوقع: لا داعي لإعادة المحاولة
        raise RuntimeError(
            f"خطأ غير متوقع ({response.status_code}): {response.text[:500]}"
        )

    raise RuntimeError(
        f"فشلت المحاولات المتكررة ({MAX_RETRIES}) بسبب ازدحام الخوادم أو تجاوز الحصة.\n"
        f"يرجى الانتظار قليلاً ثم إعادة المحاولة.\nتفاصيل آخر خطأ: {last_error_message}"
    )


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
    يولّد سيناريو قصة أطفال عبر OpenRouter (chat/completions)، ويعيد النتيجة كـ dict:
    {"title": "...", "scenes": [{"scene_number", "narration", "image_prompt"}, ...]}
    """
    payload = {
        "model": TEXT_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.9,
    }

    response = _post_with_retry(
        f"{OPENROUTER_BASE_URL}/chat/completions", api_key, payload
    )
    data = response.json()

    try:
        raw_text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise ValueError(f"استجابة غير متوقعة من النموذج: {data}") from e

    cleaned_text = _clean_json_text(raw_text)

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
    يولّد صورة واحدة لكل مشهد عبر OpenRouter Images endpoint (Gemini 2.5 Flash Image).

    Returns:
        dict بالشكل {scene_number: مسار ملف الصورة}
    """
    os.makedirs(output_dir, exist_ok=True)

    image_paths: Dict[int, str] = {}

    for scene in scenes:
        scene_number = scene.get("scene_number")
        image_prompt = scene.get("image_prompt", "").strip()

        if not image_prompt:
            continue

        payload = {
            "model": IMAGE_MODEL,
            "prompt": image_prompt,
        }

        try:
            response = _post_with_retry(
                f"{OPENROUTER_BASE_URL}/images", api_key, payload
            )
            data = response.json()
            b64_image = data["data"][0]["b64_json"]
            image_bytes = base64.b64decode(b64_image)

            file_path = os.path.join(output_dir, f"scene_{scene_number}.png")
            with open(file_path, "wb") as f:
                f.write(image_bytes)
            image_paths[scene_number] = file_path

        except Exception as e:
            raise RuntimeError(
                f"فشل توليد صورة المشهد رقم {scene_number}: {e}"
            ) from e

    return image_paths


# --------------------------------------------------------------------------
# 3) توليد التعليق الصوتي
# --------------------------------------------------------------------------
def _post_streaming_audio(url: str, api_key: str, json_payload: dict) -> bytes:
    """
    يرسل POST مع stream=True ويجمّع أجزاء الصوت (audio.data) المرسلة تباعاً
    عبر Server-Sent Events، ثم يعيد البايتات الكاملة بعد فك ترميز base64.
    بعض نماذج الصوت (مثل openai/gpt-audio-mini) لا تقبل الصوت إلا مع البث.
    """
    last_error_message = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(
                url,
                headers=_headers(api_key),
                json=json_payload,
                timeout=REQUEST_TIMEOUT_SECONDS,
                stream=True,
            )
        except requests.exceptions.RequestException as e:
            last_error_message = f"فشل الاتصال بالشبكة: {e}"
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BASE_DELAY_SECONDS * attempt)
            continue

        if response.status_code != 200:
            if response.status_code in (401, 402, 403):
                raise RuntimeError(
                    f"خطأ في المفتاح أو الرصيد ({response.status_code}): {response.text[:500]}"
                )
            if response.status_code == 404:
                raise RuntimeError(
                    f"النموذج غير موجود على OpenRouter (404): {response.text[:500]}"
                )
            if response.status_code == 429 or response.status_code >= 500:
                last_error_message = f"{response.status_code}: {response.text[:500]}"
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BASE_DELAY_SECONDS * attempt)
                continue
            raise RuntimeError(
                f"خطأ غير متوقع ({response.status_code}): {response.text[:500]}"
            )

        audio_chunks: List[bytes] = []
        try:
            for line in response.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[len("data:"):].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                audio_part = delta.get("audio")
                if audio_part and audio_part.get("data"):
                    audio_chunks.append(base64.b64decode(audio_part["data"]))
        except requests.exceptions.RequestException as e:
            last_error_message = f"انقطع البث أثناء الاستقبال: {e}"
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BASE_DELAY_SECONDS * attempt)
            continue

        if audio_chunks:
            return b"".join(audio_chunks)

        last_error_message = "لم يصل أي صوت ضمن أجزاء البث."
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BASE_DELAY_SECONDS * attempt)

    raise RuntimeError(
        f"فشلت المحاولات المتكررة ({MAX_RETRIES}) في استقبال الصوت.\n"
        f"تفاصيل آخر خطأ: {last_error_message}"
    )


def generate_audios(scenes: List[dict], output_dir: str, api_key: str) -> Dict[int, str]:
    """
    يولّد تعليقاً صوتياً واحداً لكل مشهد عبر OpenRouter chat/completions
    (بمودالية صوت وبث مباشر stream=True، وهو ما يتطلبه هذا النموذج تحديداً).

    Returns:
        dict بالشكل {scene_number: مسار ملف الصوت}
    """
    os.makedirs(output_dir, exist_ok=True)

    audio_paths: Dict[int, str] = {}

    for scene in scenes:
        scene_number = scene.get("scene_number")
        narration = scene.get("narration", "").strip()

        if not narration:
            continue

        payload = {
            "model": TTS_MODEL,
            "modalities": ["text", "audio"],
            "audio": {"voice": TTS_VOICE, "format": TTS_FORMAT},
            "stream": True,
            "messages": [
                {
                    "role": "user",
                    "content": f"اقرأ النص التالي بصوت دافئ يناسب سرد قصص للأطفال: {narration}",
                }
            ],
        }

        try:
            pcm_bytes = _post_streaming_audio(
                f"{OPENROUTER_BASE_URL}/chat/completions", api_key, payload
            )

            file_path = os.path.join(output_dir, f"scene_{scene_number}.wav")
            with wave.open(file_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # pcm16 = 2 بايت لكل عينة
                wf.setframerate(PCM_SAMPLE_RATE)
                wf.writeframes(pcm_bytes)
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
        zf.writestr("story.json", json.dumps(script, ensure_ascii=False, indent=2))

        if os.path.isdir(images_dir):
            for file_name in sorted(os.listdir(images_dir)):
                full_path = os.path.join(images_dir, file_name)
                if os.path.isfile(full_path):
                    zf.write(full_path, arcname=os.path.join("images", file_name))

        if os.path.isdir(audio_dir):
            for file_name in sorted(os.listdir(audio_dir)):
                full_path = os.path.join(audio_dir, file_name)
                if os.path.isfile(full_path):
                    zf.write(full_path, arcname=os.path.join("audio", file_name))

    return zip_path
