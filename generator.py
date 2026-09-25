# 1. توليد السيناريو عبر Gemini API
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
    
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"اكتب قصة أطفال عن: {prompt}",
        config={"response_mime_type": "application/json", "system_instruction": system_instruction}
    )
    
    return json.loads(response.text)
