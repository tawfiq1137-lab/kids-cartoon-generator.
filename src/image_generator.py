"""
image_generator.py
-------------------
Generates one illustration per scene using Pollinations.ai's free public
image API (no API key, no watermark, no login). Uses a fixed `seed` derived
from the story so re-runs of the same story keep a consistent look, and
relies on the character_bible text embedded in every prompt (see
script_generator.py) for character consistency across scenes.
"""

import hashlib
import os
import time
import urllib.parse

import requests

from . import config


def _seed_for(story_title: str) -> int:
    """Deterministic seed so all scenes of one story share a consistent visual seed base."""
    h = hashlib.sha256(story_title.encode("utf-8")).hexdigest()
    return int(h[:8], 16) % 1_000_000


def generate_image(prompt: str, story_title: str, scene_index: int, out_path: str,
                    max_retries: int = 4) -> str:
    """
    Downloads a generated image for `prompt` and saves it to `out_path`.
    Returns out_path on success. Raises on repeated failure.
    """
    base_seed = _seed_for(story_title)
    seed = base_seed + scene_index  # small offset keeps style consistent, poses varied

    encoded_prompt = urllib.parse.quote(prompt)
    url = (
        f"{config.POLLINATIONS_BASE_URL}/{encoded_prompt}"
        f"?width={config.VIDEO_WIDTH}&height={config.VIDEO_HEIGHT}"
        f"&model={config.IMAGE_MODEL}&seed={seed}&nologo=true"
    )

    last_error = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, timeout=120)
            resp.raise_for_status()
            if resp.headers.get("content-type", "").startswith("image"):
                with open(out_path, "wb") as f:
                    f.write(resp.content)
                return out_path
            last_error = RuntimeError(f"Unexpected content-type: {resp.headers.get('content-type')}")
        except Exception as e:  # noqa: BLE001
            last_error = e
        time.sleep(3 * (attempt + 1))  # backoff, the free endpoint can be briefly busy

    raise RuntimeError(f"Failed to generate image after {max_retries} attempts: {last_error}")


def generate_all_images(scenes, story_title: str, images_dir: str = None) -> list:
    """
    scenes: list of Scene objects (from script_generator.Scene)
    Returns list of file paths, one per scene, in order.
    """
    images_dir = images_dir or config.IMAGES_DIR
    os.makedirs(images_dir, exist_ok=True)

    paths = []
    for scene in scenes:
        out_path = os.path.join(images_dir, f"scene_{scene.index:02d}.png")
        generate_image(scene.image_prompt, story_title, scene.index, out_path)
        paths.append(out_path)
    return paths
