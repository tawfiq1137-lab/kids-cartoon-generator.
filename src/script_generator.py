import os
import json
import google.generativeai as genai

# استدعاء الإعدادات بطريقة آمنة لتجنب أخطاء المسارات
try:
    import config
except ImportError:
    from src import config

def generate_script(prompt_text, num_scenes=3):
    """
    توليد السيناريو والوصف الخاص بكل مشهد بناءً على فكرة المستخدم
    """
    # تهيئة مفتاح API الخاص بـ Gemini
    api_key = getattr(config, "GEMINI_API_KEY", os.getenv("GEMINI_API_KEY"))
    if not api_key:
        raise ValueError("لم يتم العثور على مفتاح GEMINI_API_KEY في ملف config أو بيئة العمل.")
        
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')

    prompt = f"""
    أنت كاتب سيناريو محترف لقصص الأطفال الكرتونية.
    اكتب سيناريو قصة طفل بناءً على الفكرة التالية: "{prompt_text}".
    المطلوب إنشاء بالضبط {num_scenes} مشاهد.
    
    أخرج النتيجة بصيغة JSON فقط بهذه الهيكلية الدقيقة بدون أي نص إضافي:
    {{
      "scenes": [
        {{
          "scene_number": 1,
          "narration": "النص الصوتي الذي سيتحدث به الراوي",
          "image_prompt": "وصف دقيق للمشهد باللغة الإنجليزية لتوليد الصورة AI cartoon style"
        }}
      ]
    }}
    """

    response = model.generate_content(prompt)
    text_response = response.text.strip()
    
    # تنظيف المخرج من علامات markdown إن وجدت
    if text_response.startswith("```json"):
        text_response = text_response[7:]
    if text_response.startswith("```"):
        text_response = text_response[3:]
    if text_response.endswith("```"):
        text_response = text_response[:-3]

    data = json.loads(text_response.strip())
    return data
