"""
video_assembler.py
------------------
Combines per-scene images, voiceover audio, and subtitle overlays into a single MP4 video.
"""

import os
from moviepy.editor import ImageClip, AudioFileClip, CompositeVideoClip, concatenate_videoclips

try:
    import config
except ImportError:
    from src import config


def _ken_burns(image_clip: ImageClip, duration: float, zoom_ratio: float = 0.08) -> ImageClip:
    def resize_fn(t):
        return 1.0 + (zoom_ratio * (t / duration))

    return image_clip.resize(resize_fn).set_duration(duration)


def build_scene_clip(image_path: str, audio_path: str, subtitle_path: str, duration: float):
    base = ImageClip(image_path).set_duration(duration)
    base = base.resize(height=config.VIDEO_HEIGHT)
    base = base.set_position("center")
    zoomed = _ken_burns(base, duration)

    subtitle_overlay = (
        ImageClip(subtitle_path)
        .set_duration(duration)
        .set_position(("center", "bottom"))
    )

    audio = AudioFileClip(audio_path)
    scene_clip = CompositeVideoClip(
        [zoomed, subtitle_overlay], size=(config.VIDEO_WIDTH, config.VIDEO_HEIGHT)
    ).set_duration(duration)
    scene_clip = scene_clip.set_audio(audio)

    return scene_clip


def compute_scene_boundaries(scenes) -> list:
    boundaries = []
    t = 0.0
    for scene in scenes:
        start = t
        end = t + scene.est_seconds
        boundaries.append((scene.index, start, end))
        t = end
    return boundaries


def assemble_video(scenes, image_paths, audio_paths, subtitle_paths, output_path: str):
    clips = []
    for scene, img_path, audio_path, sub_path in zip(scenes, image_paths, audio_paths, subtitle_paths):
        clip = build_scene_clip(img_path, audio_path, sub_path, scene.est_seconds)
        clips.append(clip)

    final = concatenate_videoclips(clips, method="compose")

    final.write_videoclip(
        output_path,
        fps=config.FPS,
        codec="libx264",
        audio_codec="aac",
        audio_bitrate="192k",
        threads=4,
        preset="medium",
    )

    for c in clips:
        c.close()
    final.close()

    scene_boundaries = compute_scene_boundaries(scenes)
    return output_path, scene_boundaries
