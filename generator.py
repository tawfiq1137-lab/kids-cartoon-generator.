"""
generator.py
------------
وحدة مسؤولة عن توليد قصص الأطفال (نص + مشاهد + أوصاف صور) باستخدام
مكتبة google-genai الجديدة، وإرجاع النتيجة كـ dict جاهز للاستخدام في app.py.
"""

import json
import re
from google import genai
from google.genai import types

MODEL_NAME = "gemini-2.5-flash"

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
- اجعل image_prompt وصفاً بصرياً بالإنجليزية يصلح لاستخدامه في نموذج توليد صور.
- تأكد أن الناتج قابل للتحويل مباشرة عبر json.loads بدون أي أخطاء.
"""


def _clean_json_text(text: str) -> str:
    """
    تنظيف النص المرتجع من النموذج من أي حشو ماركداون (```json ... ```)
    أو نصوص زائدة قبل/بعد كائن JSON، تمهيداً لتمريره إلى json.loads.
    """
    cleaned = text.strip()

    # إزالة أسوار الكود إن وجدت (```json ... ``` أو ``` ... ```)
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    # في حال وجود نص قبل/بعد كائن JSON، نحاول استخراج أول { ... } متوازن
    if not (cleaned.startswith("{") and cleaned.endswith("}")):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start:end + 1]

    return cleaned


def generate_script(prompt: str, api_key: str) -> dict:
    """
    يولّد سيناريو قصة أطفال باستخدام Gemini، ويعيد النتيجة كـ dict.

    Args:
        prompt: فكرة القصة أو الطلب الذي يزوده المستخدم.
        api_key: مفتاح Google GenAI API.

    Returns:
        dict بالشكل:
        {
            "title": "...",
            "scenes": [
                {"scene_number": 1, "narration": "...", "image_prompt": "..."},
                ...
            ]
        }

    Raises:
        ValueError: إذا فشل تحليل استجابة النموذج كـ JSON صالح.
        Exception: أي خطأ آخر ناتج عن استدعاء API (يُعاد رفعه كما هو).
    """
    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            temperature=0.9,
        ),
    )

    raw_text = response.text or ""
    cleaned_text = _clean_json_text(raw_text)

    try:
        result = json.loads(cleaned_text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"فشل تحليل استجابة النموذج كـ JSON صالح.\n"
            f"الخطأ: {e}\n"
            f"النص المستلم (بعد التنظيف): {cleaned_text[:500]}"
        ) from e

    # تحقق أساسي من بنية الناتج
    if "title" not in result or "scenes" not in result:
        raise ValueError(
            f"استجابة النموذج لا تحتوي على الحقول المطلوبة (title, scenes): {result}"
        )

    return result
