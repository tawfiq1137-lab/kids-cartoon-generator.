import os
import requests

# استدعاء الإعدادات بطريقة آمنة لتجنب أخطاء المسارات النسبية
try:
    import config
except ImportError:
    from src import config


def _seed_for(story_title: str) -> int:
    """توليد seed ثابت بناءً على عنوان القصة لضمان تناسق الصور"""
    return sum(ord(c) for c in story_title) % 100000


def generate_images(script_data, output_dir="generated_images"):
    """توليد صور المشاهد بناءً على الوصف الموجود في script_data"""
    os.makedirs(output_dir, exist_ok=True)
    images_paths = []

    scenes = script_data.get("scenes", [])
    title = script_data.get("title", "cartoon_story")
    seed = _seed_for(title)

    for scene in scenes:
        scene_num = scene.get("scene_number", 1)
        prompt = scene.get("image_prompt", "")

        # إضافة طابع كرتوني ثابت وموحد للقصة
        full_prompt = f"Kids storybook illustration, vibrant colors, cute cartoon style, {prompt}"
        encoded_prompt = requests.utils.quote(full_prompt)

        # استخدام خدمة Pollinations لتوليد الصور بدون تعقيد
        image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1280&height=720&seed={seed}&nologo=true"

        response = requests.get(image_url)
        if response.status_code == 200:
            file_path = os.path.join(output_dir, f"scene_{scene_num}.png")
            with open(file_path, "wb") as f:
                f.write(response.content)
            images_paths.append(file_path)
        else:
            raise Exception(f"فشل في توليد الصورة للمشهد {scene_num}")

    return images_paths
