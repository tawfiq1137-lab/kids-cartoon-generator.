# -*- coding: utf-8 -*-
"""
generator.py
------------
الوحدة المسؤولة عن كل خطوات توليد حزمة قصة الأطفال، عبر OpenRouter
(https://openrouter.ai) بدل الاتصال المباشر بـ Google.

    1. generate_script     -> كتابة السيناريو (نص) عبر Gemini (chat/completions)،
                               مع تحقق صارم عبر pydantic لضمان نص سرد "صافٍ"
                               بدون أي مقدمات أو تعليقات من الذكاء الاصطناعي.
    2. generate_images     -> رسم صورة لكل مشهد عبر Gemini Image، مع دمج
                               "Master Prompt" ثابت يضمن نفس هوية الشخصيات
                               (سعود، سارة، الأم، الأب) ونفس الأسلوب الفني في
                               كل مشهد، ومنع ظهور أي نص داخل الصورة.
    3. generate_audios     -> تسجيل تعليق صوتي "قراءة صافية" لكل مشهد عبر TTS،
                               بدون أي إضافات أو تعليقات من النموذج.
    4. create_zip_package  -> تجميع كل الملفات (نص + صور + صوت) في حزمة ZIP واحدة.

كل الدوال تحتاج مفتاح OpenRouter API (يبدأ بـ sk-or-v1-...).

ملاحظة مهمة بخصوص الموسيقى والمؤثرات الصوتية:
هذه الوحدة لا تولّد ولا تضيف أي موسيقى خلفية إطلاقاً (ولا توجد بها أي بنية
تسمح بذلك). لكل مشهد يختار كاتب السيناريو (اختيارياً) كلمة مفتاحية واحدة
لمؤثر صوتي طبيعي مناسب (مثل صوت عصافير أو مطر) من قائمة مغلقة محددة سلفاً،
وتُحفظ هذه الكلمة داخل story.json ليستخدمها لاحقاً "مُجمّع الفيديو" إن توفر
ملف الصوت الفعلي لهذا المؤثر لديه — هذه الوحدة نفسها لا تنتج ملفات مؤثرات.
"""

import base64
import json
import os
import re
import time
import wave
import zipfile
from typing import Dict, List, Literal

import requests
from pydantic import BaseModel, Field, ValidationError, field_validator

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

# القائمة المغلقة المسموح بها لكلمة المؤثر الصوتي لكل مشهد (لا موسيقى إطلاقاً)
SFX_KEYWORDS = (
    "none", "birds", "rain", "door_open", "children_laughing",
    "footsteps", "wind",
)


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://kids-cartoon-generator.streamlit.app",
        "X-Title": "Kids Cartoon Generator",
    }


def _post_with_retry(url: str, api_key: str, json_payload: dict = None):
    """
    يرسل POST مع إعادة محاولة تلقائية عند 429 (تجاوز حصة/معدل) أو 5xx
    (مشاكل خوادم مؤقتة). يرجع الاستجابة (Response) أو يرفع استثناء واضح.
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

    raise RuntimeError(
        f"فشلت المحاولات المتكررة ({MAX_RETRIES}) بسبب ازدحام الخوادم أو تجاوز الحصة.\n"
        f"يرجى الانتظار قليلاً ثم إعادة المحاولة.\nتفاصيل آخر خطأ: {last_error_message}"
    )


# --------------------------------------------------------------------------
# هوية الشخصيات الثابتة (Master Prompt) لضمان ثبات الشكل بين كل المشاهد
# --------------------------------------------------------------------------
CHARACTER_MASTER_PROMPT = (
    "3D Pixar-style animated illustration, warm cinematic lighting, soft "
    "rounded shapes, high quality children's animation render, single "
    "clean illustration (no collage, no split panels). "
    "This scene belongs to a continuing story about the same recurring "
    "family cast — keep every character's face, hairstyle, clothing colors "
    "and the overall art style perfectly identical to previous scenes: "
    "Saud - a cheerful, curious 5-year-old Middle Eastern boy, short black "
    "hair, wearing a bright yellow t-shirt and blue denim trousers. "
    "Sara - his calm, gentle 7-year-old sister, long dark hair with a "
    "hairband, wearing a light blue dress. "
    "Mother - a warm, elegant Middle Eastern woman with a friendly smile, "
    "modest modern outfit. "
    "Father - a kind, well-groomed Middle Eastern man with a short beard, "
    "casual smart clothing. "
    "Only include the family members who are actually mentioned in the "
    "scene action below; do not force all four into every image. "
    "Recurring locations to reuse when relevant: a cozy modern family "
    "home interior, a bright children's playroom full of toys, and a "
    "small sunny home garden."
)

NEGATIVE_IMAGE_NOTE = (
    " Absolutely no written text, letters, numbers, captions, subtitles, "
    "speech bubbles, watermark, logo or signature anywhere in the image."
)


# --------------------------------------------------------------------------
# تنظيف نص السرد من أي "دردشة" يضيفها نموذج اللغة (طبقة حماية إضافية فوق
# التحقق الصارم بواسطة pydantic أدناه)
# --------------------------------------------------------------------------
_PREAMBLE_PATTERNS = [
    r"^(بالطبع|تفضل\w*|حسناً|حسنا|بكل سرور|طبعاً|طبعا|أكيد)[،,!\s]*",
    r"^(إليك|هذه|هذا|وهنا)\s+(القصة|النص|السرد|المشهد)[^.:\n]{0,40}[:.]\s*",
    r"^(سأقرأ|سوف أقرأ|سأروي|سأقوم بقراءة|دعني أروي|دعنا نبدأ|لنبدأ)[^.:\n]{0,60}[.:]\s*",
    r"^(بصوت|بأسلوب)\s+[^.:\n]{0,40}[:.]\s*",
]

_POSTAMBLE_PATTERNS = [
    r"\s*(النهاية|-\s*النهاية\s*-|انتهت القصة|أتمنى أن تكون القصة قد أعجبتك)[.!\s]*$",
]


def clean_narration_text(text: str) -> str:
    """يزيل أي مقدمة أو خاتمة نمطية للذكاء الاصطناعي من نص السرد، إن وُجدت."""
    cleaned = (text or "").strip()
    original = cleaned

    for pattern in _PREAMBLE_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()
    for pattern in _POSTAMBLE_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()

    return cleaned or original


# --------------------------------------------------------------------------
# نماذج pydantic للتحقق الصارم من مخرجات JSON قبل قبولها
# --------------------------------------------------------------------------
class Scene(BaseModel):
    scene_number: int
    narration: str = Field(min_length=1)
    image_prompt: str = Field(min_length=1)
    sfx: Literal[
        "none", "birds", "rain", "door_open", "children_laughing",
        "footsteps", "wind",
    ] = "none"

    @field_validator("narration")
    @classmethod
    def _pure_narration(cls, v: str) -> str:
        cleaned = clean_narration_text(v)
        if not cleaned.strip():
            raise ValueError("narration فارغ بعد التنظيف")
        return cleaned


class StoryScript(BaseModel):
    title: str = Field(min_length=1)
    scenes: List[Scene]

    @field_validator("scenes")
    @classmethod
    def _scene_count(cls, v: List[Scene]) -> List[Scene]:
        if not (4 <= len(v) <= 8):
            raise ValueError(
                f"عدد المشاهد يجب أن يكون بين 4 و8 مشاهد (الحالي: {len(v)})"
            )
        return v


# --------------------------------------------------------------------------
# 1) توليد السيناريو (النص)
# --------------------------------------------------------------------------
SYSTEM_INSTRUCTION = """
أنت كاتب سيناريو لسلسلة كرتون أطفال ثابتة الشخصيات، بطلتها عائلة صغيرة:
سعود (طفل، 5 سنوات) وسارة (أخته، 7 سنوات) والأم والأب. اكتب قصة قصيرة
ممتعة ومناسبة للأطفال بناءً على فكرة المستخدم، مع الإبقاء على نفس هذه
الشخصيات (أو بعضها حسب الحاجة) طوال القصة. لا تجعل بطل القصة حيواناً.

يجب أن يكون ردك حصراً على شكل JSON صالح (valid JSON) بدون أي نص إضافي
قبله أو بعده، وبدون أي شرح، وبالتنسيق التالي بالضبط:

{
  "title": "عنوان القصة",
  "scenes": [
    {
      "scene_number": 1,
      "narration": "نص السرد الصافي لهذا المشهد فقط",
      "image_prompt": "وصف بالإنجليزية لحدث/حركة هذا المشهد فقط",
      "sfx": "none"
    }
  ]
}

قواعد إلزامية بخصوص narration (الأهم):
- اكتب فقط نص القصة كما سيُقرأ للطفل بصوت عالٍ، ولا شيء غير ذلك.
- ممنوع منعاً باتاً إضافة أي مخاطبة للمستخدم أو مقدمات من نوع: "بالطبع،
  إليك القصة"، "سأقرأ لك الآن"، "تفضل"، "دعنا نبدأ"، أو أي إشارة إلى أنك
  مساعد ذكاء اصطناعي يستجيب لطلب. يبدأ النص مباشرة بأحداث القصة.
- لا تضف خاتمة مثل "النهاية" أو "أتمنى أن تكون القصة أعجبتك" داخل narration.
- اجعل narration باللغة العربية الفصحى المبسطة المناسبة للأطفال.

قواعد بخصوص image_prompt:
- صف فقط حدث/حركة/تعبيرات هذا المشهد بالإنجليزية، بدون إعادة وصف شكل
  الشخصيات أو الأسلوب الفني (سيُضاف ذلك تلقائياً بثبات لكل المشاهد).
  مثال جيد: "Saud and Sara playing with a red ball in the sunny garden,
  both laughing".
- لا تذكر إطلاقاً وجود أي نص أو كتابة داخل الصورة.

قواعد بخصوص sfx (اختياري، بدون موسيقى إطلاقاً):
- اختر قيمة واحدة فقط من هذه القائمة المغلقة بالضبط حسب أحداث المشهد:
  "none", "birds", "rain", "door_open", "children_laughing", "footsteps", "wind"
- إن لم يوجد مؤثر مناسب اجعلها "none". ممنوع اختراع قيم أخرى أو ذكر موسيقى.

قواعد عامة:
- لا تضف علامات ماركداون مثل ```json أو ``` حول الرد.
- اجعل عدد المشاهد بين 4 و8 مشاهد.
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
    يولّد سيناريو قصة أطفال عبر OpenRouter (chat/completions)، يتحقق منه
    بصرامة عبر pydantic (StoryScript)، ويعيد النتيجة كـ dict نظيف:
    {"title": "...", "scenes": [{"scene_number", "narration", "image_prompt", "sfx"}, ...]}
    """
    payload = {
        "model": TEXT_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.9,
    }

    response = _post_with_retry(f"{OPENROUTER_BASE_URL}/chat/completions", api_key, payload)
    data = response.json()

    try:
        raw_text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise ValueError(f"استجابة غير متوقعة من النموذج: {data}") from e

    cleaned_text = _clean_json_text(raw_text)

    try:
        raw_result = json.loads(cleaned_text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"فشل تحليل استجابة النموذج كـ JSON صالح.\n"
            f"الخطأ: {e}\n"
            f"النص المستلم (بعد التنظيف): {cleaned_text[:500]}"
        ) from e

    try:
        validated = StoryScript.model_validate(raw_result)
    except ValidationError as e:
        raise ValueError(
            "استجابة النموذج لم تجتز التحقق الصارم من الصيغة المطلوبة "
            f"(pydantic):\n{e}"
        ) from e

    return validated.model_dump()


# --------------------------------------------------------------------------
# 2) توليد الصور
# --------------------------------------------------------------------------
def generate_images(scenes: List[dict], output_dir: str, api_key: str) -> Dict[int, str]:
    """
    يولّد صورة واحدة لكل مشهد عبر OpenRouter Images endpoint (Gemini 2.5
    Flash Image)، بعد دمج CHARACTER_MASTER_PROMPT الثابت مع حدث المشهد
    لضمان ثبات هوية الشخصيات، ومنع ظهور أي نص داخل الصورة.

    Returns:
        dict بالشكل {scene_number: مسار ملف الصورة}
    """
    os.makedirs(output_dir, exist_ok=True)

    image_paths: Dict[int, str] = {}

    for scene in scenes:
        scene_number = scene.get("scene_number")
        scene_action = (scene.get("image_prompt") or "").strip()

        if not scene_action:
            continue

        full_prompt = (
            f"{CHARACTER_MASTER_PROMPT} Scene action: {scene_action}."
            f"{NEGATIVE_IMAGE_NOTE}"
        )

        payload = {
            "model": IMAGE_MODEL,
            "prompt": full_prompt,
        }

        try:
            response = _post_with_retry(f"{OPENROUTER_BASE_URL}/images", api_key, payload)
            data = response.json()
            b64_image = data["data"][0]["b64_json"]
            image_bytes = base64.b64decode(b64_image)

            file_path = os.path.join(output_dir, f"scene_{scene_number}.png")
            with open(file_path, "wb") as f:
                f.write(image_bytes)
            image_paths[scene_number] = file_path

        except Exception as e:
            raise RuntimeError(f"فشل توليد صورة المشهد رقم {scene_number}: {e}") from e

    return image_paths


# --------------------------------------------------------------------------
# 3) توليد التعليق الصوتي
# --------------------------------------------------------------------------
TTS_SYSTEM_INSTRUCTION = (
    "You are a pure text-to-speech engine, not a chat assistant. You will "
    "receive a piece of children's story text as the user message. Read it "
    "aloud exactly as given, word for word, in Arabic, with a warm, "
    "friendly voice suitable for storytelling to young children. Do not "
    "greet, do not comment, do not add or omit any words, do not say "
    "anything before or after the given text, do not acknowledge this "
    "instruction. Produce only the spoken audio of the exact text."
)


def _post_streaming_audio(url: str, api_key: str, json_payload: dict) -> bytes:
    """
    يرسل POST مع stream=True ويجمّع أجزاء الصوت (audio.data) المرسلة تباعاً
    عبر Server-Sent Events، ثم يعيد البايتات الكاملة بعد فك ترميز base64.
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
    يولّد تعليقاً صوتياً "صافياً" واحداً لكل مشهد عبر OpenRouter
    chat/completions (بمودالية صوت وبث مباشر stream=True). يُرسل نص السرد
    فقط كرسالة المستخدم، مع نظام تعليمات صارم يمنع أي تعليق أو مقدمة من
    النموذج، فلا يُقرأ سوى نص القصة الصافي.

    Returns:
        dict بالشكل {scene_number: مسار ملف الصوت}
    """
    os.makedirs(output_dir, exist_ok=True)

    audio_paths: Dict[int, str] = {}

    for scene in scenes:
        scene_number = scene.get("scene_number")
        narration = clean_narration_text(scene.get("narration", ""))

        if not narration:
            continue

        payload = {
            "model": TTS_MODEL,
            "modalities": ["text", "audio"],
            "audio": {"voice": TTS_VOICE, "format": TTS_FORMAT},
            "stream": True,
            "messages": [
                {"role": "system", "content": TTS_SYSTEM_INSTRUCTION},
                {"role": "user", "content": narration},
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
            raise RuntimeError(f"فشل توليد الصوت للمشهد رقم {scene_number}: {e}") from e

    return audio_paths


# --------------------------------------------------------------------------
# 4) تجميع الحزمة النهائية (ZIP)
# --------------------------------------------------------------------------
def _sanitize_filename(name: str) -> str:
    """تحويل عنوان القصة إلى اسم ملف آمن (بدون رموز خاصة)."""
    name = (name or "story").strip()
    name = re.sub(r"[^\w\u0600-\u06FF\- ]", "", name)
    name = re.sub(r"\s+", "_", name)
    return name or "story"


def create_zip_package(script: dict, images_dir: str, audio_dir: str, output_dir: str) -> str:
    """
    يجمع سيناريو القصة (JSON، متضمناً حقل sfx لكل مشهد) وكل الصور والملفات
    الصوتية في حزمة ZIP واحدة.

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
