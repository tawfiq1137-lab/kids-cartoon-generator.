import streamlit as st
import os
import shutil
import tempfile
import traceback

from generator import generate_script, generate_images, generate_audios, create_zip_package

# --------------------------------------------------------------------------
# إعدادات الصفحة
# --------------------------------------------------------------------------
st.set_page_config(
    page_title="مولد حزمة قصص الأطفال",
    page_icon="🎨",
    layout="centered",
)

st.title("🎨 مولد حزمة قصص الأطفال")
st.write("أنشئ النص، والصور، والصوت لقصتك في ثوانٍ، وقم بتحميلها كحزمة جاهزة للمونتاج!")

# --------------------------------------------------------------------------
# تهيئة session_state
# --------------------------------------------------------------------------
if "zip_file" not in st.session_state:
    st.session_state.zip_file = None
if "zip_bytes" not in st.session_state:
    st.session_state.zip_bytes = None
if "story_title" not in st.session_state:
    st.session_state.story_title = "story"
if "work_dir" not in st.session_state:
    st.session_state.work_dir = None


def cleanup_work_dir():
    """تنظيف مجلد العمل المؤقت الخاص بالجلسة الحالية إن وُجد."""
    work_dir = st.session_state.get("work_dir")
    if work_dir and os.path.exists(work_dir):
        shutil.rmtree(work_dir, ignore_errors=True)
    st.session_state.work_dir = None


# --------------------------------------------------------------------------
# نموذج الإدخال
# --------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ الإعدادات")
    api_key = st.text_input("مفتاح Gemini API:", type="password")
    st.caption("لن يتم تخزين المفتاح؛ يُستخدم فقط أثناء هذه الجلسة.")

prompt = st.text_area(
    "فكرة القصة:",
    placeholder="مثال: قصة أرنب صغير يتعلم أصل الصدق والوفاء بالعهد",
    height=100,
)

col1, col2 = st.columns([3, 1])
with col1:
    generate_clicked = st.button("🚀 بدء توليد الحزمة", type="primary", use_container_width=True)
with col2:
    reset_clicked = st.button("🔄 قصة جديدة", use_container_width=True)

if reset_clicked:
    cleanup_work_dir()
    st.session_state.zip_file = None
    st.session_state.zip_bytes = None
    st.session_state.story_title = "story"
    st.rerun()

# --------------------------------------------------------------------------
# منطق التوليد
# --------------------------------------------------------------------------
if generate_clicked:
    api_key = (api_key or "").strip()
    prompt = (prompt or "").strip()

    if not api_key:
        st.error("⚠️ يرجى إدخال مفتاح Gemini API أولاً!")
    elif not prompt:
        st.error("⚠️ يرجى إدخال فكرة القصة!")
    elif len(prompt) < 5:
        st.error("⚠️ فكرة القصة قصيرة جداً، يرجى كتابة وصف أوضح.")
    else:
        # تنظيف أي حزمة سابقة قبل البدء من جديد
        cleanup_work_dir()
        st.session_state.zip_file = None
        st.session_state.zip_bytes = None

        work_dir = tempfile.mkdtemp(prefix="story_")
        st.session_state.work_dir = work_dir
        images_dir = os.path.join(work_dir, "images")
        audio_dir = os.path.join(work_dir, "audio")

        status = st.status("جاري إعداد القصة...", expanded=True)
        try:
            status.write("📝 1. جاري كتابة السيناريو بالذكاء الاصطناعي...")
            script = generate_script(prompt, api_key)

            if not script.get("scenes"):
                raise ValueError("لم يتم توليد أي مشاهد للقصة، حاول بفكرة أخرى.")

            status.write("🖼️ 2. جاري رسم صور المشاهد...")
            img_paths = generate_images(script["scenes"], images_dir)

            status.write("🎙️ 3. جاري تسجيل التعليق الصوتي...")
            audio_paths = generate_audios(script["scenes"], audio_dir)

            status.write("📦 4. جاري ضغط جميع الملفات في حزمة ZIP...")
            zip_file = create_zip_package(script, images_dir, audio_dir)

            # نقرأ محتوى الملف في الذاكرة فوراً حتى يبقى زر التحميل يعمل
            # حتى بعد أي إعادة تحديث لاحقة للصفحة
            with open(zip_file, "rb") as f:
                st.session_state.zip_bytes = f.read()

            st.session_state.zip_file = zip_file
            st.session_state.story_title = script.get("title", "story")

            status.update(label="✅ اكتمل توليد الحزمة بنجاح!", state="complete")

        except ValueError as e:
            status.update(label="❌ خطأ في بيانات القصة", state="error")
            st.error(f"تفاصيل الخطأ: {e}")
        except Exception as e:
            status.update(label="❌ حدث خطأ أثناء التوليد", state="error")
            st.error(f"تفاصيل الخطأ: {e}")
            with st.expander("عرض التفاصيل التقنية (Traceback)"):
                st.code(traceback.format_exc())

# --------------------------------------------------------------------------
# زر التحميل (يظهر طالما توجد حزمة جاهزة في الجلسة)
# --------------------------------------------------------------------------
if st.session_state.zip_bytes:
    st.divider()
    st.subheader(f"📖 {st.session_state.story_title}")
    st.download_button(
        label="⬇️ تحميل حزمة القصة (ZIP)",
        data=st.session_state.zip_bytes,
        file_name=f"{st.session_state.story_title}.zip",
        mime="application/zip",
        use_container_width=True,
    )
