"""
Kids Cartoon Video Generator — Streamlit App
=============================================
Paste a topic (or a full draft script) and get back:
  1. A ~2 minute Arabic narrated cartoon video (script -> images -> voiceover
     -> subtitles -> MP4), and
  2. 3-4 automatically extracted vertical (9:16) "shorts" cut along scene
     boundaries, ready for YouTube Shorts / TikTok / Reels.
No background music is ever added, in either output. No paid/watermarked
services are used.
"""

import os
import shutil
import time
import traceback

import streamlit as st

from src import config
from src.script_generator import generate_story_package
from src.image_generator import generate_all_images
from src.tts_generator import generate_all_voiceovers
from src.subtitle_utils import render_all_subtitles
from src.video_assembler import assemble_video
from src.shorts_extractor import extract_shorts

st.set_page_config(page_title="Kids Cartoon Video Generator", page_icon="🎬", layout="centered")

st.title("🎬 Kids Cartoon Video Generator")
st.caption(
    "Topic or script → automated ~2 min Arabic cartoon video. "
    "Voice + natural sound effects only — never background music."
)

with st.sidebar:
    st.header("Settings")
    voice_label = st.selectbox("Narrator voice", list(config.ARABIC_VOICES.keys()), index=0)
    voice = config.ARABIC_VOICES[voice_label]
    st.markdown("---")
    st.markdown(
        "**Free stack used:**\n"
        "- Script: Google Gemini (free tier)\n"
        "- Images: Pollinations.ai (free, no watermark)\n"
        "- Voice: edge-tts (free, no watermark)\n"
        "- Assembly: moviepy / ffmpeg\n"
        "- Shorts: moviepy center-crop to 9:16, no new deps"
    )
    if not config.GEMINI_API_KEY:
        st.warning("GEMINI_API_KEY not set. Add it in Settings → Secrets before generating.")

topic = st.text_area(
    "Topic or draft script",
    placeholder="e.g. أرنب صغير يتعلم مشاركة ألعابه مع أصدقائه في الغابة",
    height=150,
)

run_button = st.button("Generate video", type="primary", disabled=not topic.strip())

if "run_id" not in st.session_state:
    st.session_state.run_id = 0

if run_button:
    st.session_state.run_id += 1
    run_id = st.session_state.run_id
    run_dir = os.path.join(config.WORKDIR, f"run_{run_id}")
    images_dir = os.path.join(run_dir, "images")
    audio_dir = os.path.join(run_dir, "audio")
    subs_dir = os.path.join(run_dir, "subtitles")
    output_path = os.path.join(config.OUTPUT_DIR, f"story_{run_id}.mp4")

    progress = st.progress(0, text="Starting...")

    try:
        progress.progress(5, text="Writing script and scene breakdown...")
        package = generate_story_package(topic)
        st.subheader(package.title)
        with st.expander("Character bible (kept identical across every scene)"):
            st.write(package.character_bible)
        with st.expander(f"Scenes ({len(package.scenes)})"):
            for s in package.scenes:
                st.markdown(f"**Scene {s.index + 1}:** {s.narration_ar}")

        progress.progress(25, text="Generating illustrations for each scene...")
        image_paths = generate_all_images(package.scenes, package.title, images_dir)

        progress.progress(55, text="Generating Arabic voiceover for each scene...")
        audio_paths = generate_all_voiceovers(package.scenes, audio_dir, voice=voice)

        progress.progress(75, text="Rendering subtitles...")
        subtitle_paths = render_all_subtitles(package.scenes, subs_dir)

        progress.progress(85, text="Assembling final video (no music, ever)...")
        long_video_path, scene_boundaries = assemble_video(
            package.scenes, image_paths, audio_paths, subtitle_paths, output_path
        )

        progress.progress(93, text="Extracting vertical shorts (9:16) for Reels/TikTok/Shorts...")
        shorts_dir = os.path.join(run_dir, config.SHORTS_DIRNAME)
        short_paths = extract_shorts(long_video_path, scene_boundaries, shorts_dir)

        progress.progress(100, text="Done!")
        st.success("Long video and shorts generated successfully.")

        st.subheader("🎥 Full story video")
        st.video(long_video_path)
        with open(long_video_path, "rb") as f:
            st.download_button("Download full MP4", f, file_name=f"{package.title}.mp4", mime="video/mp4")

        st.subheader(f"📱 Auto-generated shorts ({len(short_paths)})")
        st.caption("Vertical 9:16, center-cropped, same voice + captions, still no music.")
        for i, short_path in enumerate(short_paths, start=1):
            st.markdown(f"**Short {i}**")
            st.video(short_path)
            with open(short_path, "rb") as f:
                st.download_button(
                    f"Download short_scene_{i}.mp4",
                    f,
                    file_name=f"short_scene_{i}.mp4",
                    mime="video/mp4",
                    key=f"short_dl_{run_id}_{i}",
                )

    except Exception as e:  # noqa: BLE001
        progress.empty()
        st.error(f"Generation failed: {e}")
        st.code(traceback.format_exc())
