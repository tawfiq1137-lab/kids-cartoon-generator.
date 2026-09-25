import json
import os
import zipfile
import asyncio
import requests
import edge_tts
from google import genai

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

# 2. توليد الصور عبر Pollinations AI
def generate_images(scenes: list, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    image_paths = []
    
    for scene in scenes:
        num = scene["scene_number"]
        prompt = scene["image_prompt"]
        full_prompt = f"Kids storybook illustration, vibrant colors, cute 2D cartoon style, {prompt}"
        encoded_prompt = requests.utils.quote(full_prompt)
        
        url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1280&height=720&nologo=true"
        res = requests.get(url)
        
        if res.status_code == 200:
            path = os.path.join(output_dir, f"scene_{num:02d}.png")
            with open(path, "wb") as f:
                f.write(res.content)
            image_paths.append(path)
            
    return image_paths

# 3. توليد الصوت عبر Edge-TTS
async def _synth_audio(text, path):
    communicate = edge_tts.Communicate(text, voice="ar-SA-HamedNeural")
    await communicate.save(path)

def generate_audios(scenes: list, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    audio_paths = []
    
    for scene in scenes:
        num = scene["scene_number"]
        text = scene["narration"]
        path = os.path.join(output_dir, f"scene_{num:02d}.mp3")
        
        asyncio.run(_synth_audio(text, path))
        audio_paths.append(path)
        
    return audio_paths

# 4. ضغط الحزمة في ملف ZIP
def create_zip_package(script, img_dir, audio_dir, zip_path="story_package.zip"):
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # إضافة السيناريو
        script_path = "script.json"
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(script, f, ensure_ascii=False, indent=2)
        zipf.write(script_path, arcname="script.json")
        os.remove(script_path)
        
        # إضافة الصور
        for root, _, files in os.walk(img_dir):
            for file in files:
                zipf.write(os.path.join(root, file), arcname=os.path.join("images", file))
                
        # إضافة الأصوات
        for root, _, files in os.walk(audio_dir):
            for file in files:
                zipf.write(os.path.join(root, file), arcname=os.path.join("audio", file))
                
    return zip_path
