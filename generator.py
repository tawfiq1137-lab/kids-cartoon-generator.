import json
from google import genai

def generate_script(prompt: str, api_key: str) -> dict:
        client = genai.Client(api_key=api_key)
    
    system_instruction = """
    You are a professional children story writer. Write a short story based on the prompt.
    Return JSON format only:
    {
      "title": "Story Title",
      "scenes": [
        {
          "scene_number": 1,
          "narration": "Arabic text for narration",
          "image_prompt": "English detailed prompt for image generation, cute 2D cartoon style"
        }
      ]
    }
    """
    
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"Write a children story in Arabic about: {prompt}\n\n{system_instruction}"
    )
    
    text_response = response.text
    if text_response.startswith("```json"):
        text_response = text_response.replace("```json", "").replace("```", "").strip()
        
    return json.loads(text_response)
