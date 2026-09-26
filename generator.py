import json
from google import genai

def generate_script(prompt, api_key):
    client = genai.Client(api_key=api_key)
    system_instruction = "Write a short kids story in Arabic. Return JSON: {\"title\": \"...\", \"scenes\": [{\"scene_number\": 1, \"narration\": \"...\", \"image_prompt\": \"...\"}]}"
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"{prompt}\n{system_instruction}"
    )
    text = response.text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)
