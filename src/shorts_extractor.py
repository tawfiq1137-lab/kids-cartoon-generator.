"""
shorts_extractor.py
-------------------
Extracts vertical (9:16) shorts from the main video.
"""

import os
from moviepy.editor import VideoFileClip
import moviepy.video.fx.all as vfx

try:
    import config
except ImportError:
    from src import config


def group_scenes_into_clips(scene_boundaries: list) -> list:
    min_dur = config.SHORTS_MIN_SECONDS
    max_dur = config.SHORTS_MAX_SECONDS

    groups = []
    current_indices = []
    current_start = None

    for scene_index, start, end in scene_boundaries:
        if current_start is None:
            current_start = start
        current_indices.append(scene_index)
        current_duration = end - current_start

        is_last_scene = scene_index == scene_boundaries[-1][0]

        if current_duration >= min_dur or is_last_scene:
            if current_duration <= max_dur:
                groups.append((current_start, end, list(current_indices)))
                current_indices = []
                current_start = None

    return groups


def _center_crop_to_vertical(clip: VideoFileClip) -> VideoFileClip:
    target_ratio = 9 / 16
    src_w, src_h = clip.w, clip.h

    crop_w = int(src_h * target_ratio)
    if crop_w > src_w:
        crop_w = src_w
        crop_h = int(src_w / target_ratio)
    else:
        crop_h = src_h

    x_center = src_w / 2
    y_center = src_h / 2

    cropped = clip.fx(
        vfx.crop,
        x1=x_center - crop_w / 2,
        y1=y_center - crop_h / 2,
        width=crop_w,
        height=crop_h,
    )

    return cropped.resize((config.SHORTS_WIDTH, config.SHORTS_HEIGHT))


def extract_shorts(video_path: str, scene_boundaries: list, output_dir: str) -> list:
    os.makedirs(output_dir, exist_ok=True)
    groups = group_scenes_into_clips(scene_boundaries)
    shorts_paths = []

    with VideoFileClip(video_path) as full_video:
        for idx, (start_time, end_time, _) in enumerate(groups, 1):
            subclip = full_video.subclip(start_time, end_time)
            vertical_clip = _center_crop_to_vertical(subclip)

            out_path = os.path.join(output_dir, f"short_{idx:02d}.mp4")
            vertical_clip.write_videofile(
                out_path,
                fps=config.FPS,
                codec="libx264",
                audio_codec="aac",
                audio_bitrate="192k",
                threads=4,
                preset="medium",
            )
            vertical_clip.close()
            subclip.close()
            shorts_paths.append(out_path)

    return shorts_paths
