"""
shorts_extractor.py
--------------------
Automatically turns the finished long-form (16:9) story video into 3-4
vertical (9:16) "shorts" suitable for YouTube Shorts / TikTok.

How it works:
  1. group_scenes_into_clips(): walks the scene boundary list produced by
     video_assembler.compute_scene_boundaries() and greedily packs whole
     scenes together until each group is between SHORTS_MIN_SECONDS and
     SHORTS_MAX_SECONDS long, aiming for 3-4 groups total. Scenes are never
     split mid-sentence, so voice + burned-in captions stay intact.
  2. extract_shorts(): for each group, takes a sub-clip of the ALREADY
     RENDERED long video (which already contains voice-only audio and the
     colorful Arabic subtitles burned into the frames — see
     video_assembler.py), center-crops it from 16:9 to 9:16, resizes to
     1080x1920, and writes it to config.SHORTS_OUTPUT_DIR.

Because every short is just a re-encoded sub-clip of the final long video,
the "no background music" and "expressive Arabic captions" guarantees carry
over automatically — there is no code path here that adds any new audio or
strips subtitles.
"""

import os

from moviepy.editor import VideoFileClip
from moviepy.video.fx.all import crop, resize

from . import config


def group_scenes_into_clips(scene_boundaries: list) -> list:
    """
    scene_boundaries: list of (scene_index, start_time, end_time), in order,
        as produced by video_assembler.compute_scene_boundaries().

    Returns a list of (start_time, end_time, scene_indices) groups, each
    ideally between SHORTS_MIN_SECONDS and SHORTS_MAX_SECONDS long, with the
    total number of groups aimed at SHORTS_TARGET_MIN_CLIPS..MAX_CLIPS.
    """
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
            # Close this group now if we're in range, if adding more would
            # blow past max_dur, or if we've run out of scenes.
            next_would_exceed_max = False
            next_idx_pos = scene_boundaries.index((scene_index, start, end)) + 1
            if next_idx_pos < len(scene_boundaries):
                _, _, next_end = scene_boundaries[next_idx_pos]
                next_would_exceed_max = (next_end - current_start) > max_dur

            if current_duration <= max_dur and (next_would_exceed_max or is_last_scene or current_duration >= min_dur):
                groups.append((current_start, end, list(current_indices)))
                current_indices = []
                current_start = None
            elif current_duration > max_dur:
                # A single scene alone already exceeds max_dur (rare, long
                # narration): ship it as its own short rather than dropping it.
                groups.append((current_start, end, list(current_indices)))
                current_indices = []
                current_start = None

    # Merge smallest adjacent groups if we ended up with more than the target
    # max clip count, to keep the output focused on the top viral moments.
    while len(groups) > config.SHORTS_TARGET_MAX_CLIPS and len(groups) > 1:
        # find the adjacent pair with the smallest combined duration
        best_i, best_combined = 0, float("inf")
        for i in range(len(groups) - 1):
            combined = groups[i + 1][1] - groups[i][0]
            if combined < best_combined:
                best_combined = combined
                best_i = i
        a_start, _, a_idx = groups[best_i]
        _, b_end, b_idx = groups[best_i + 1]
        merged = (a_start, b_end, a_idx + b_idx)
        groups[best_i:best_i + 2] = [merged]

    return groups


def _center_crop_to_vertical(clip: VideoFileClip) -> VideoFileClip:
    """Crops the horizontal clip to a 9:16 window centered on the frame
    (where characters are framed in this project's illustration style),
    then resizes to the standard vertical shorts resolution."""
    target_ratio = 9 / 16
    src_w, src_h = clip.w, clip.h

    crop_w = int(src_h * target_ratio)
    if crop_w > src_w:
        # source is already narrower than target ratio; crop height instead
        crop_w = src_w
        crop_h = int(src_w / target_ratio)
    else:
        crop_h = src_h

    x_center = src_w / 2
    y_center = src_h / 2

    cropped = crop(
        clip,
        width=crop_w,
        height=crop_h,
        x_center=x_center,
        y_center=y_center,
    )
    vertical = resize(cropped, newsize=(config.SHORTS_WIDTH, config.SHORTS_HEIGHT))
    return vertical


def extract_shorts(long_video_path: str, scene_boundaries: list, output_dir: str = None) -> list:
    """
    Produces 3-4 vertical short clips from the finished long video.
    Returns a list of output file paths.
    """
    output_dir = output_dir or config.SHORTS_OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)

    groups = group_scenes_into_clips(scene_boundaries)

    output_paths = []
    source = VideoFileClip(long_video_path)

    try:
        for i, (start, end, scene_indices) in enumerate(groups, start=1):
            sub = source.subclip(start, min(end, source.duration))
            vertical = _center_crop_to_vertical(sub)

            out_path = os.path.join(output_dir, f"short_scene_{i}.mp4")
            vertical.write_videofile(
                out_path,
                fps=config.FPS,
                codec="libx264",
                audio_codec="aac",       # carries over the existing voice-only audio
                audio_bitrate="192k",
                threads=4,
                preset="medium",
            )
            vertical.close()
            output_paths.append(out_path)
    finally:
        source.close()

    return output_paths
