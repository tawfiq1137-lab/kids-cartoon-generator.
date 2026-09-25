"""
tts_generator.py
----------------
Generates natural-sounding Arabic voiceover per scene using edge-tts.
"""

import asyncio
import os
import edge_tts
from moviepy.editor import AudioFileClip

try:
    import config
except ImportError:
    from src import config


async def _synthesize(text: str, out_path: str, voice: str, rate: str, pitch: str):
    communicate = edge_tts.Communicate(text, voice=voice, rate=rate, pitch=pitch)
    await communicate.save(out_path)


def generate_voiceover(text: str, out_path: str, voice: str = None) -> float:
    """
    Synthesizes 'text' to 'out_path' (.mp3) and returns its duration in seconds.
    """
    voice = voice or config.DEFAULT_VOICE
    asyncio.run(_synthesize(text, out_path, voice, config.TTS_RATE, config.TTS_PITCH))

    with AudioFileClip(out_path) as clip:
        duration = clip.duration
    return duration


def generate_all_voiceovers(scenes, audio_dir: str = None, voice: str = None) -> list:
    """
    Returns list of audio file paths, one per scene, in order.
    """
    audio_dir = audio_dir or config.AUDIO_DIR
    os.makedirs(audio_dir, exist_ok=True)

    paths = []
    for scene in scenes:
        out_path = os.path.join(audio_dir, f"scene_{scene.index:02d}.mp3")
        real_duration = generate_voiceover(scene.narration_ar, out_path, voice=voice)
        scene.est_seconds = round(real_duration, 1)
        paths.append(out_path)
    return paths
