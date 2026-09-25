"""
tts_generator.py
-----------------
Generates natural-sounding Arabic voiceover per scene using edge-tts
(Microsoft's free neural voices, no API key, no watermark, no music).
Only speech is produced here — no background audio is mixed in this module,
by design, so the "no music" rule can never be broken at this stage.
"""

import asyncio
import os

import edge_tts
from moviepy.editor import AudioFileClip

from . import config


async def _synthesize(text: str, out_path: str, voice: str, rate: str, pitch: str):
    communicate = edge_tts.Communicate(text, voice=voice, rate=rate, pitch=pitch)
    await communicate.save(out_path)


def generate_voiceover(text: str, out_path: str, voice: str = None) -> float:
    """
    Synthesizes `text` to `out_path` (mp3) and returns its duration in seconds.
    """
    voice = voice or config.DEFAULT_VOICE
    asyncio.run(_synthesize(text, out_path, voice, config.TTS_RATE, config.TTS_PITCH))

    with AudioFileClip(out_path) as clip:
        duration = clip.duration
    return duration


def generate_all_voiceovers(scenes, audio_dir: str = None, voice: str = None) -> list:
    """
    scenes: list of Scene objects (mutated in place: est_seconds updated to the
            REAL spoken duration so video timing matches the audio exactly).
    Returns list of audio file paths, one per scene, in order.
    """
    audio_dir = audio_dir or config.AUDIO_DIR
    os.makedirs(audio_dir, exist_ok=True)

    paths = []
    for scene in scenes:
        out_path = os.path.join(audio_dir, f"scene_{scene.index:02d}.mp3")
        real_duration = generate_voiceover(scene.narration_ar, out_path, voice=voice)
        scene.est_seconds = round(real_duration, 2)
        paths.append(out_path)
    return paths
