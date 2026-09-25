import os
import sys
import io
import json
import zipfile
import streamlit as st

# إضافة المجلد الرئيسي ومجلد src لمسارات بايثون لمنع أخطاء ImportError
root_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(root_dir, "src")

if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

# استدعاء وحدات التوليد
try:
    from script_generator import generate_script
    from image_generator import generate_images
    from tts_generator import generate_audio
    from subtitle_utils import generate_subtitles
except ImportError:
    from src.script_generator import generate_script
    from src.image_generator import generate_images
    from src.tts_generator import generate_audio
    from src.subtitle_utils import generate_subtitles

st.set_page_config(page_title="Kids Cartoon Generator - Phase 1", page_icon="🎨", layout="centered")

st.title("🎨 مولّد مشاهد الكرتون (الأداة الأولى)")
st.write("قم بتوليد النص، الصور، والأصوات واستخرجها في حزمة مضغوطة جاهزة للمونتاج.")

# مدخلات المستخدم
prompt = st.text_area("أدخل فكرة القصة أو السيناريو:", placeholder="مثال: قصة قصيرة عن أرنب شجاع يتعلم الصدق...")
num_scenes = st.slider("عدد المشاهد:", min_value=1, max_value=10, value=3)

if st.button("🚀 بدء توليد الحزمة", type="primary"):
    if not prompt.strip():
        st.warning("رجاءً أدخل فكرة القصة أولاً.")
    else:
        try:
            with st.spinner("1️⃣ جاري كتابة السيناريو..."):
                script_data = generate_script(prompt, num_scenes)
                st.success("تم توليد السيناريو بنجاح!")

            with st.spinner("2️⃣ جاري توليد وتجهيز الصور..."):
                images_paths = generate_images(script_data)
                st.success("تم توليد الصور بنجاح!")

            with st.spinner("3️⃣ جاري إنشاء الأصوات البشرية والتحقق منها..."):
                audio_paths = generate_audio(script_data)
                st.success("تم توليد الأصوات بنجاح!")

            with st.spinner("4️⃣ جاري إنتاج ملفات الترجمة والتوقيت..."):
                subtitle_paths = generate_subtitles(script_data)

            # ضغط جميع المخرجات في ذاكرة الرام (In-Memory ZIP) لتجنب استهلاك القرص الصلب
            with st.spinner("📦 جاري تجميع الحزمة في ملف ZIP..."):
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                    # إضافة ملف السيناريو بصيغة JSON
                    zip_file.writestr("script.json", json.dumps(script_data, ensure_ascii=False, indent=2))
                    
                    # إضافة الصور
                    for img_path in images_paths:
                        if os.path.exists(img_path):
                            zip_file.write(img_path, arcname=f"images/{os.path.basename(img_path)}")
                            
                    # إضافة الأصوات
                    for aud_path in audio_paths:
                        if os.path.exists(aud_path):
                            zip_file.write(aud_path, arcname=f"audio/{os.path.basename(aud_path)}")
                            
                    # إضافة الترجمات
                    for sub_path in subtitle_paths:
                        if os.path.exists(sub_path):
                            zip_file.write(sub_path, arcname=f"subtitles/{os.path.basename(sub_path)}")

                zip_buffer.seek(0)

            st.balloons()
            st.success("✨ اكتملت الحزمة بنجاح وخفيفة جداً على السيرفر!")
            
            # زر تحميل الـ ZIP مباشرة على الجوال
            st.download_button(
                label="📥 تحميل حزمة المشروع (ZIP)",
                data=zip_buffer,
                file_name="cartoon_assets_bundle.zip",
                mime="application/zip",
                use_container_width=True
            )

        except Exception as e:
            st.error(f"حدث خطأ أثناء التوليد: {str(e)}")
