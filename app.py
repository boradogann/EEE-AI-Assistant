import streamlit as st
import os
from PIL import Image
from pypdf import PdfReader
from google import genai
from google.genai import types

# Sayfa yapılandırması
st.set_page_config(
    page_title="EE Mühendislik Asistanı Pro",
    page_icon="⚡",
    layout="wide"
)

# Metin akarken sayfanın aşağıya zorla kaymasını engelleyen stil
st.markdown(
    """
    <style>
    html { scroll-behavior: auto !important; }
    .main { overflow-anchor: none !important; }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("⚡ Elektrik-Elektronik Mühendisi Asistanı (Pro)")
st.caption("Devre analizi, şema/görsel yorumlama ve teknik datasheet (RAG) danışmanı.")

# API Anahtarı kontrolü (Streamlit Secrets / Ortam Değişkeni)
api_key = os.environ.get("GOOGLE_API_KEY")
if not api_key:
    # Streamlit Cloud'da Secrets doğrudan st.secrets altından da okunabilir
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
    else:
        st.error("API Anahtarı bulunamadı. Lütfen Streamlit Secrets alanına GOOGLE_API_KEY tanımlayın.")
        st.stop()

client = genai.Client(api_key=api_key)

# ----------------- SOL MENÜ: DOSYA YÜKLEME ALANI -----------------
with st.sidebar:
    st.header("📁 Mühendislik Araçları")
    
    # 1. Devre Şeması / PCB Görseli Yükleme
    st.subheader("🖼️ Devre / Şema Analizi")
    uploaded_image = st.file_uploader("Görsel Yükle (PNG, JPG)", type=["png", "jpg", "jpeg"])
    if uploaded_image:
        image_preview = Image.open(uploaded_image)
        st.image(image_preview, caption="Yüklenen Devre Görseli", use_container_width=True)
    
    # 2. PDF / Datasheet Yükleme (RAG)
    st.subheader("📄 Datasheet / Not Yükle (PDF)")
    uploaded_pdf = st.file_uploader("Teknik Döküman (PDF)", type=["pdf"])
    pdf_text_context = ""
    if uploaded_pdf:
        with st.spinner("PDF dökümanı okunuyor ve analiz ediliyor..."):
            reader = PdfReader(uploaded_pdf)
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    pdf_text_context += text + "\n"
        st.success(f"PDF Yüklendi! ({len(reader.pages)} sayfa döküman aktif)")

# ----------------- SISTEM TALİMATI VE BAĞLAM -----------------
base_system_instruction = """
Sen kıdemli bir Elektrik-Elektronik Mühendisi teknik asistanısın. 
Görevin sadece ve sadece Elektrik-Elektronik Mühendisliği alanındaki konulara (devre analizi, gömülü sistemler, mikrodenetleyiciler, güç elektroniği, kontrol sistemleri, sinyal işleme, PLC, telekomünikasyon vb.) teknik ve analitik bir yaklaşımla yanıt vermektir.

Kurallar:
1. Yanıtların teknik, formüllere dayalı, mühendislik standartlarına uygun ve analitik olsun.
2. Kullanıcı devre şeması veya görsel yüklediyse; komponentleri, bağlantı mantığını, olası tasarım hatalarını ve filtreleme yapılarını adım adım açıkla.
3. Kullanıcı PDF/Datasheet yüklediyse; öncelikle o dökümandaki pin konfigürasyonlarına, elektriksel karakteristiklere ve register tablolarına sadık kalarak cevap ver.
4. Kullanıcı önceki sorulara veya hesaplamalara atıfta bulunursa geçmiş konuşma bağlamını kullanarak devam et.
5. Elektrik-elektronik mühendisliği alanı dışındaki (tarih, yemek tarifleri, genel sohbet, magazin, siyaset vb.) hiçbir soruya ASLA cevap verme. Bu tür durumlarda: "Ben yalnızca Elektrik-Elektronik Mühendisliği alanındaki teknik soruları yanıtlamak üzere programlandım." diyerek reddet.
"""

# PDF içeriğini prompt bağlamına ekleme
if pdf_text_context:
    effective_instruction = base_system_instruction + f"\n\n[YÜKLENEN REFERANS DATASHEET / DÖKÜMAN]:\n{pdf_text_context[:40000]}"
else:
    effective_instruction = base_system_instruction

# ----------------- HAFIZA YAPILANDIRMASI -----------------
if "messages" not in st.session_state:
    st.session_state.messages = []

if "GOOGLE_history" not in st.session_state:
    st.session_state.GOOGLE_history = []

# Mesaj geçmişini ekrana bas
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ----------------- SOHBET DÖNGÜSÜ -----------------
if user_input := st.chat_input("Teknik sorunuzu yazın..."):
    # Kullanıcı arayüzü bildirimi
    display_text = user_input
    if uploaded_image:
        display_text = f"🖼️ *[Devre Görseli Eklendi]* {user_input}"
    if uploaded_pdf:
        display_text = f"📄 *[Datasheet Aktif]* {display_text}"
        
    st.session_state.messages.append({"role": "user", "content": display_text})
    with st.chat_message("user"):
        st.markdown(display_text)

    # GOOGLE için girdi parçalarını (parts) hazırlama
    parts = []
    
    # Görsel varsa binary olarak ekle
    if uploaded_image:
        img_bytes = uploaded_image.getvalue()
        parts.append(types.Part.from_bytes(data=img_bytes, mime_type=uploaded_image.type))
    
    # Metin girdisini ekle
    parts.append(types.Part.from_text(text=user_input))

    # Hafızaya ekle
    st.session_state.GOOGLE_history.append(types.Content(role="user", parts=parts))

    # Canlı akış (Streaming) yanıtı
    with st.chat_message("assistant"):
        def stream_generator():
            response_stream = client.models.generate_content_stream(
                model="GOOGLE-3.6-flash",
                contents=st.session_state.GOOGLE_history,
                config=types.GenerateContentConfig(
                    system_instruction=effective_instruction,
                    temperature=0.2,
                )
            )
            for chunk in response_stream:
                if chunk.text:
                    yield chunk.text

        full_response = st.write_stream(stream_generator())

    # Model cevabını kaydet
    st.session_state.messages.append({"role": "assistant", "content": full_response})
    st.session_state.GOOGLE_history.append(
        types.Content(
            role="model",
            parts=[types.Part.from_text(text=full_response)]
        )
    )
