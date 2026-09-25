"""
script_generator.py
--------------------
Turns a raw topic (or a raw script) into:
  1. A "character bible" (fixed description of each character, used verbatim
     in every scene's image prompt so the character stays visually consistent).
  2. A list of scenes, each with:
       - narration text (Arabic, for TTS)
       - an image generation prompt (character bible + scene action/location)
       - an approximate target duration in seconds

Uses Google Gemini's free tier (google-generativeai). If no API key is set,
raises a clear error rather than silently producing placeholder content.
"""

import json
import re
from dataclasses import dataclass, field
from typing import List

import google.generativeai as genai

from . import config


@dataclass
class Scene:
    index: int
    narration_ar: str
    image_prompt: str
    est_seconds: float = 0.0


@dataclass
class StoryPackage:
    title: str
    character_bible: str
    scenes: List[Scene] = field(default_factory=list)


SYSTEM_INSTRUCTIONS = """You are a professional children's story writer and storyboard artist
for short animated videos (ages 4-9). You write in Modern Standard Arabic (fus-ha simplified,
easy for kids to understand), warm and positive tone, no violence, no scary content.

You must return ONLY valid JSON, no markdown fences, no commentary, matching exactly this schema:

{
  "title": "string - short title in Arabic",
  "character_bible": "string - one paragraph in English describing every recurring character's
       fixed visual appearance (species/age, exact colors, clothing, distinguishing features).
       This paragraph will be repeated in every single image prompt, so it must be short but
       precise and must never change between scenes.",
  "scenes": [
    {
      "narration_ar": "string - 1 to 3 short Arabic sentences of narration/dialogue for this scene",
      "action_and_setting_en": "string in English - what happens in this scene and where,
           written for an image generation model (setting, action, mood, camera framing).
           Do NOT repeat the character description here, only the action/setting."
    }
  ]
}

Rules:
- Produce between {min_scenes} and {max_scenes} scenes that together tell a complete short story
  with a beginning, a small problem/adventure, and a happy resolution.
- Keep narration simple and read-aloud friendly; total narration across all scenes should take
  roughly {target_seconds} seconds to speak aloud (~2.4 words/second average Arabic narration pace).
- Never include song lyrics or references to background music; the video will have voice and
  ambient sound effects only, never music.
- Never mention brand names, real people, or copyrighted characters.
"""


def _build_prompt(topic_or_script: str) -> str:
    return SYSTEM_INSTRUCTIONS.format(
        min_scenes=config.MIN_SCENES,
        max_scenes=config.MAX_SCENES,
        target_seconds=config.TARGET_TOTAL_SECONDS,
    ) + f"\n\nUser's topic or draft script:\n\"\"\"\n{topic_or_script}\n\"\"\"\n"


def _extract_json(text: str) -> dict:
    """Gemini sometimes wraps JSON in ```json fences despite instructions; strip them."""
    cleaned = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    return json.loads(cleaned)


def generate_story_package(topic_or_script: str) -> StoryPackage:
    if not config.GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Get a free key at https://google.com "
            "and set it as an environment variable or Streamlit secret."
        )

    genai.configure(api_key=config.GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-1.5-flash")

    response = model.generate_content(
        _build_prompt(topic_or_script),
        generation_config={"temperature": 0.9, "max_output_tokens": 4096},
    )
    data = _extract_json(response.text)

    total_words = sum(len(s["narration_ar"].split()) for s in data["scenes"])
    words_per_second = 2.4

    scenes = []
    for i, raw_scene in enumerate(data["scenes"]):
        est_seconds = max(2.5, len(raw_scene["narration_ar"].split()) / words_per_second)
        image_prompt = (
            f"{data['character_bible']}. Scene: {raw_scene['action_and_setting_en']}. "
            f"{config.IMAGE_STYLE_SUFFIX}"
        )
        scenes.append(
            Scene(
                index=i,
                narration_ar=raw_scene["narration_ar"].strip(),
                image_prompt=image_prompt,
                est_seconds=round(est_seconds, 2),
            )
        )

    return StoryPackage(
        title=data["title"],
        character_bible=data["character_bible"],
        scenes=scenes,
    )
