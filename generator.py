# 1. توليد السيناريو عبر Gemini API (باستخدام Interactions API الحديثة)
def generate_script(prompt: str, api_key: str) -> dict:
    client = genai.Client(api_key=api_key)
    
    system_instruction = """
    أنت مؤلف قصص أطفال محترف. قم بكتابة قصة أطفال قصيرة وممتعة بناءً على الطلب.
    يجب أن ترجع النتيجة بصيغة JSON حصراً بالهيكل التالي:
    {
      "title": "عنوان القصة",
      "scenes": [
        {
          "scene_number": 1,
          "narration": "النص العربي الصريح الموجه للأطفال للراوي",
          "image_prompt": "English detailed prompt for image generation, cute 2D cartoon style"
        }
      ]
    }
    """
    
    interaction = client.interactions.create(
        model="gemini-2.5-flash",
        input=f"اكتب قصة أطفال عن: {prompt}\n\n{system_instruction}"
    )
    
    # تنظيف النص واستخراج الـ JSON
    text_response = interaction.outputs[-1].text
    if text_response.startswith("```json"):
        text_response = text_response.replace("```json", "").replace("```", "").strip()
        
    return json.loads(text_response)
