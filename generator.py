# -*- coding: utf-8 -*-
"""
generator.py
------------
الوحدة المسؤولة عن كل خطوات توليد حزمة قصة الأطفال، عبر OpenRouter
(https://openrouter.ai) بدل الاتصال المباشر بـ Google.

    1. generate_script     -> كتابة السيناريو، مقسّماً إلى أسطر حوار لكل
                               مشهد، كل سطر منسوب لمتحدث محدد (راوٍ/سعود/
                               سارة/الأم/الأب)، مع تحقق صارم عبر pydantic.
    2. generate_images     -> رسم صورة لكل مشهد، مع "Master Prompt" ثابت
                               يضمن نفس هوية الشخصيات في كل مشهد، ومنع أي
                               نص داخل الصورة.
    3. generate_audios     -> تسجيل تعليق صوتي منفصل لكل سطر حوار بصوت
                               ونبرة تناسب المتحدث (راوٍ/طفل/طفلة/أم/أب)،
                               ثم دمج أسطر كل مشهد في ملف صوتي واحد مع
                               حساب مدة كل سطر بدقة تامة (لا تقدير) لاستخدامها
                               لاحقاً في مزامنة الترجمة سطراً بسطر.
    4. create_zip_package  -> تجميع كل الملفات (نص + صور + صوت) في حزمة ZIP.

كل الدوال تحتاج مفتاح OpenRouter API (يبدأ بـ sk-or-v1-...).

ملاحظة بخصوص الموسيقى والمؤثرات الصوتية:
هذه الوحدة لا تولّد ولا تضيف أي موسيقى خلفية إطلاقاً. لكل مشهد يختار كاتب
السيناريو (اختيارياً) كلمة مفتاحية واحدة لمؤثر صوتي طبيعي مناسب من قائمة
مغلقة محددة سلفاً، تُحفظ داخل story.json ليستخدمها "مُجمّع الفيديو" إن
توفر ملف الصوت الفعلي لهذا المؤثر لديه.
"""

import base64
import json
import os
import re
import time
import wave
import zipfile
from typing import Dict, List, Literal, Optional, Tuple

import requests
from pydantic import BaseModel, Field, ValidationError, field_validator

# --------------------------------------------------------------------------
# إعدادات OpenRouter
# --------------------------------------------------------------------------
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

TEXT_MODEL = "google/gemini-2.5-flash"
IMAGE_MODEL = "google/gemini-2.5-flash-image"
TTS_MODEL = "openai/gpt-audio-mini"
TTS_FORMAT = "pcm16"
PCM_SAMPLE_RATE = 24000  # التردد القياسي المستخدم في مخرجات صوت OpenAI
PCM_SAMPLE_WIDTH = 2     # بايتان لكل عينة (pcm16)

# الفاصل الزمني الصامت بين سطرين متتاليين داخل نفس المشهد (بالثواني)
LINE_GAP_SECONDS = 0.35

MAX_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 3
REQUEST_TIMEOUT_SECONDS = 120

# القائمة المغلقة المسموح بها لكلمة المؤثر الصوتي لكل مشهد (لا موسيقى إطلاقاً)
SFX_KEYWORDS = (
    "none", "birds", "rain", "door_open", "children_laughing",
    "footsteps", "wind", "blocks",
)

# --------------------------------------------------------------------------
# أصوات ونبرات كل متحدث (نفس محرك TTS، بصوت وأسلوب مختلف لكل شخصية)
# --------------------------------------------------------------------------
SPEAKER_VOICES = {
    "narrator": "fable",
    "saud": "alloy",
    "sara": "nova",
    "mother": "shimmer",
    "father": "onyx",
}

SPEAKER_STYLE_HINTS = {
    "narrator": (
        "narrate in a warm, engaging, story-telling tone with gentle, "
        "expressive pacing, suitable for narrating a children's story."
    ),
    "saud": (
        "voice a cheerful, energetic, curious young boy around 5 years old, "
        "with a light, playful, slightly high-pitched child-like tone."
    ),
    "sara": (
        "voice a calm, sweet young girl around 7 years old, with a gentle, "
        "warm, slightly high-pitched child-like tone."
    ),
    "mother": (
        "voice a warm, tender, caring mother, with a soft and affectionate "
        "tone."
    ),
    "father": (
        "voice a kind, gentle father, with a warm, calm, slightly deeper "
        "and reassuring tone."
    ),
}


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
# تنظيف نص الحوار من أي "دردشة" يضيفها نموذج اللغة، ومن علامات الاقتباس
# (طبقة حماية إضافية فوق التحقق الصارم بواسطة pydantic أدناه)
# --------------------------------------------------------------------------
_PREAMBLE_PATTERNS = [
    r"^(بالطبع|تفضل\w*|حسناً|حسنا|بكل سرور|طبعاً|طبعا|أكيد)[،,!\s]*",
    r"^(إليك|هذه|هذا|وهنا)\s+(القصة|النص|السرد|المشهد|الجملة)[^.:\n]{0,40}[:.]\s*",
    r"^(سأقرأ|سوف أقرأ|سأروي|سأقوم بقراءة|دعني أروي|دعنا نبدأ|لنبدأ)[^.:\n]{0,60}[.:]\s*",
    r"^(بصوت|بأسلوب)\s+[^.:\n]{0,40}[:.]\s*",
]

_POSTAMBLE_PATTERNS = [
    r"\s*(النهاية|-\s*النهاية\s*-|انتهت القصة|أتمنى أن تكون القصة قد أعجبتك)[.!\s]*$",
]

# علامات اقتباس/تنصيص بأشكالها المختلفة — غير مسموح بها داخل نص أي سطر لأن
# نسبة الحوار للمتحدث تغني عنها تماماً، ووجودها يسبب تشوهاً بصرياً في
# النصوص العربية ثنائية الاتجاه (RTL) عند حرقها كترجمة.
_QUOTE_CHARS_RE = re.compile(r"[\"'`\u00b4\u2018\u2019\u201c\u201d\u00ab\u00bb]")


def clean_narration_text(text: str) -> str:
    """يزيل أي مقدمة أو خاتمة نمطية للذكاء الاصطناعي، وأي علامات اقتباس."""
    cleaned = (text or "").strip()
    original = cleaned

    for pattern in _PREAMBLE_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()
    for pattern in _POSTAMBLE_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()

    cleaned = _QUOTE_CHARS_RE.sub("", cleaned).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)

    return cleaned or _QUOTE_CHARS_RE.sub("", original).strip()


# --------------------------------------------------------------------------
# نماذج pydantic للتحقق الصارم من مخرجات JSON قبل قبولها
# --------------------------------------------------------------------------
SpeakerType = Literal["narrator", "saud", "sara", "mother", "father"]


class NarrationLine(BaseModel):
    speaker: SpeakerType = "narrator"
    text: str = Field(min_length=1)
    # تُملأ لاحقاً (بعد توليد الصوت) بالمدة الفعلية بالثواني لهذا السطر
    duration: Optional[float] = None

    @field_validator("text")
    @classmethod
    def _pure_text(cls, v: str) -> str:
        cleaned = clean_narration_text(v)
        if not cleaned.strip():
            raise ValueError("نص السطر فارغ بعد التنظيف")
        return cleaned


class Scene(BaseModel):
    scene_number: int
    narration_lines: List[NarrationLine] = Field(min_length=1)
    image_prompt: str = Field(min_length=1)
    sfx: Literal[
        "none", "birds", "rain", "door_open", "children_laughing",
        "footsteps", "wind", "blocks",
    ] = "none"


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
      "narration_lines": [
        {"speaker": "narrator", "text": "جملة سرد وصفية"},
        {"speaker": "saud", "text": "جملة حوار قالها سعود"}
      ],
      "image_prompt": "وصف بالإنجليزية لحدث/حركة هذا المشهد فقط",
      "sfx": "none"
    }
  ]
}

قواعد إلزامية بخصوص narration_lines (الأهم):
- قسّم كل مشهد إلى أسطر قصيرة (جملة واحدة أو جملتان لكل سطر)، وانسب كل سطر
  لصاحبه عبر حقل speaker الذي يجب أن يكون بالضبط واحداً من:
  "narrator" (للسرد الوصفي العام)، "saud"، "sara"، "mother"، "father".
- استخدم "narrator" لوصف الأحداث، واستخدم اسم الشخصية فقط عندما تتكلم هي
  فعلاً (حوار مباشر).
- لا تضع علامات اقتباس أو تنصيص من أي نوع حول الحوار داخل text — نسبة
  السطر لصاحبه عبر speaker تكفي تماماً، والاقتباس ممنوع كتابياً.
- اكتب في كل text نصاً صافياً فقط كما سيُقرأ بصوت عالٍ، بدون أي مخاطبة
  للمستخدم أو مقدمات من نوع: "بالطبع، إليك القصة"، "سأقرأ لك الآن"، أو أي
  إشارة إلى أنك مساعد ذكاء اصطناعي يستجيب لطلب.
- لا تضف خاتمة مثل "النهاية" داخل أي سطر.
- استخدم العربية الفصحى المبسطة المناسبة للأطفال، وتجنب علامات التشكيل
  النادرة (اكتف بالتشكيل الأساسي إن احتجت، بدون رموز نادرة قد لا تدعمها
  كل الخطوط).

قواعد بخصوص image_prompt:
- صف فقط حدث/حركة/تعبيرات هذا المشهد بالإنجليزية، بدون إعادة وصف شكل
  الشخصيات أو الأسلوب الفني (سيُضاف ذلك تلقائياً بثبات لكل المشاهد).
  مثال جيد: "Saud and Sara building a tall tower of colorful blocks
  together, both smiling".
- لا تذكر إطلاقاً وجود أي نص أو كتابة داخل الصورة.

قواعد بخصوص sfx (اختياري، بدون موسيقى إطلاقاً):
- اختر قيمة واحدة فقط من هذه القائمة المغلقة بالضبط حسب أحداث المشهد:
  "none", "birds", "rain", "door_open", "children_laughing", "footsteps",
  "wind", "blocks"
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
    بصرامة عبر pydantic (StoryScript)، ويعيد النتيجة كـ dict نظيف.
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
    يولّد صورة واحدة لكل مشهد، بعد دمج CHARACTER_MASTER_PROMPT الثابت مع
    حدث المشهد لضمان ثبات هوية الشخصيات، ومنع ظهور أي نص داخل الصورة.
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
# 3) توليد التعليق الصوتي (سطراً بسطر، بصوت مختلف لكل متحدث)
# --------------------------------------------------------------------------
def _tts_system_instruction(speaker: str) -> str:
    hint = SPEAKER_STYLE_HINTS.get(speaker, SPEAKER_STYLE_HINTS["narrator"])
    return (
        "You are a pure text-to-speech engine, not a chat assistant. You "
        "will receive a short piece of children's story text as the user "
        f"message. Read it aloud exactly as given, word for word, in "
        f"Arabic. {hint} Do not greet, do not comment, do not add or omit "
        "any words, do not say anything before or after the given text, "
        "do not acknowledge this instruction. Produce only the spoken "
        "audio of the exact text."
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


def _synthesize_line(text: str, speaker: str, api_key: str) -> bytes:
    """يولّد صوت PCM16/24kHz خام لسطر حوار واحد، بصوت ونبرة صاحب السطر."""
    payload = {
        "model": TTS_MODEL,
        "modalities": ["text", "audio"],
        "audio": {"voice": SPEAKER_VOICES.get(speaker, "alloy"), "format": TTS_FORMAT},
        "stream": True,
        "messages": [
            {"role": "system", "content": _tts_system_instruction(speaker)},
            {"role": "user", "content": text},
        ],
    }
    return _post_streaming_audio(f"{OPENROUTER_BASE_URL}/chat/completions", api_key, payload)


def generate_audios(
    scenes: List[dict], output_dir: str, api_key: str
) -> Tuple[Dict[int, str], Dict[int, dict]]:
    """
    يولّد صوتاً منفصلاً لكل سطر حوار (بصوت مناسب للمتحدث)، ثم يدمج أسطر كل
    مشهد في ملف صوتي واحد (بفاصل صمت قصير LINE_GAP_SECONDS بين الأسطر)،
    مع حساب مدة كل سطر بدقة تامة من عدد العينات الفعلي (لا تقدير إطلاقاً).

    Returns:
        (audio_paths, line_timing) حيث:
        - audio_paths: {scene_number: مسار ملف صوت المشهد الكامل (wav)}
        - line_timing: {scene_number: {"lines": [{"speaker","text","duration"}, ...],
                                        "gap_seconds": float}}
    """
    os.makedirs(output_dir, exist_ok=True)

    audio_paths: Dict[int, str] = {}
    line_timing: Dict[int, dict] = {}

    for scene in scenes:
        scene_number = scene.get("scene_number")
        lines = scene.get("narration_lines") or []
        if not lines:
            continue

        line_pcms: List[bytes] = []
        line_meta: List[dict] = []

        for line in lines:
            speaker = line.get("speaker", "narrator")
            text = clean_narration_text(line.get("text", ""))
            if not text:
                continue
            try:
                pcm_bytes = _synthesize_line(text, speaker, api_key)
            except Exception as e:
                raise RuntimeError(
                    f"فشل توليد الصوت لسطر ({speaker}) في المشهد رقم {scene_number}: {e}"
                ) from e

            duration = len(pcm_bytes) / (PCM_SAMPLE_WIDTH * PCM_SAMPLE_RATE)
            line_pcms.append(pcm_bytes)
            line_meta.append({
                "speaker": speaker,
                "text": text,
                "duration": round(duration, 3),
            })

        if not line_pcms:
            continue

        gap_samples = int(round(LINE_GAP_SECONDS * PCM_SAMPLE_RATE))
        gap_bytes = b"\x00" * (gap_samples * PCM_SAMPLE_WIDTH)
        merged_pcm = gap_bytes.join(line_pcms)

        file_path = os.path.join(output_dir, f"scene_{scene_number}.wav")
        with wave.open(file_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(PCM_SAMPLE_WIDTH)
            wf.setframerate(PCM_SAMPLE_RATE)
            wf.writeframes(merged_pcm)

        audio_paths[scene_number] = file_path
        line_timing[scene_number] = {
            "lines": line_meta,
            "gap_seconds": LINE_GAP_SECONDS,
        }

    return audio_paths, line_timing


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
    يجمع سيناريو القصة (JSON، متضمناً narration_lines بمددها الفعلية بعد
    توليد الصوت) وكل الصور والملفات الصوتية في حزمة ZIP واحدة.
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
