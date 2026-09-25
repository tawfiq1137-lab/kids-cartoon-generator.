import streamlit as st
import os
import shutil
from generator import generate_script, generate_images, generate_audios, create_zip_package

st.set_page_config(page_title="توليد حزمة قصص الأطفال", page_icon="🎨", layout="centered")

st.title("🎨 مولد حزم قصص الأطفال")
st.write("أنشئ النص، الصور، والصوت لقصتك في ثوانٍ وقم بتحميلها كحزمة جاهزة للمونتاج!")

api_key = st.text_input("مفتاح Gemini API:", type="password")
prompt = st.text_area("فكرة القصة:", placeholder="مثال: قصة أرنب صغير يتعلم أصل الصدق والوفاء بالعهد")

if st.button("🚀 بدء توليد الحزمة", type="primary"):
    if not api_key:
        st.error("يرجى إدخال مفتاح Gemini API أولاً!")
    elif not prompt:
        st.error("يرجى إدخال فكرة القصة!")
    else:
        status = st.status("جاري إعداد القصة...", expanded=True)
        try:
            status.write("📝 1. جاري كتابة السيناريو بالذكاء الاصطناعي...")
            script = generate_script(prompt, api_key)
            
            status.write("🖼️ 2. جاري رسم صور المشاهد...")
            img_paths = generate_images(script["scenes"], "temp_images")
            
            status.write("🎙️ 3. جاري تسجيل التعليق الصوتي الصريح...")
            audio_paths = generate_audios(script["scenes"], "temp_audio")
            
            status.write("📦 4. جاري ضغط جميع الملفات في حزمة ZIP...")
            zip_file = create_zip_package(script, "temp_images", "temp_audio")
            
            status.update(label="✅ اكتمل توليد الحزمة بنجاح!", state="complete")
            
            # زر التحميل
            with open(zip_file, "rb") as f:
                st.download_button(
                    label="📥 تحميل حزمة القصة (ZIP)",
                    data=f,
                    file_name=f"{script.get('title', 'story')}.zip",
                    mime="application/zip"
                )
                
            # تنظيف الملفات المؤقتة
            shutil.rmtree("temp_images", ignore_errors=True)
            shutil.rmtree("temp_audio", ignore_errors=True)
            if os.path.exists(zip_file):
                os.remove(zip_file)
                
        except Exception as e:
            status.update(label="❌ حدث خطأ أثناء التوليد!", state="error")
            st.error(f"تفاصيل الخطأ: {str(e)}")
