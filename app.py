import streamlit as st
import os
import json
from datetime import datetime
from PIL import Image
from pypdf import PdfReader
from google import genai
from google.genai import types
from google.genai import errors

# Firebase Admin SDK
import firebase_admin
from firebase_admin import credentials, firestore

st.set_page_config(
    page_title="EE Mühendislik Asistanı Pro",
    page_icon="⚡",
    layout="wide"
)

# Metin akarken sayfanın aşağıya kaymasını engelleyen stil
st.markdown(
    """
    <style>
    html { scroll-behavior: auto !important; }
    .main { overflow-anchor: none !important; }
    </style>
    """,
    unsafe_allow_html=True
)

# ----------------- 1. FIREBASE BAĞLANTISI -----------------
@st.cache_resource
def init_firebase():
    if not firebase_admin._apps:
        if "FIREBASE_KEY" in st.secrets:
            try:
                key_data = st.secrets["FIREBASE_KEY"]
                if isinstance(key_data, str):
                    key_dict = json.loads(key_data)
                else:
                    key_dict = dict(key_data)
                cred = credentials.Certificate(key_dict)
            except Exception as e:
                st.error(f"Firebase anahtarı çözümlenemedi: {e}")
                st.stop()
        elif os.path.exists("firebase_key.json"):
            cred = credentials.Certificate("firebase_key.json")
        else:
            st.error("Firebase anahtarı bulunamadı! Lütfen Streamlit Secrets alanına FIREBASE_KEY tanımlayın.")
            st.stop()
        firebase_admin.initialize_app(cred)
    return firestore.client()

db = init_firebase()

# ----------------- 2. GOOGLE CLIENT -----------------
api_key = os.environ.get("GOOGLE_API_KEY")
if not api_key:
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"].strip()
    else:
        st.error("GOOGLE_API_KEY bulunamadı. Lütfen Streamlit Secrets alanına tanımlayın.")
        st.stop()

client = genai.Client(api_key=api_key)

# ----------------- 3. KULLANICI & SOHBET GEÇMİŞİ -----------------
query_params = st.query_params
url_user = query_params.get("user", None)

if "active_username" not in st.session_state:
    st.session_state.active_username = url_user if url_user else "muhendis_1"

with st.sidebar:
    st.header("👤 Kullanıcı Profili")
    
    username_input = st.text_input(
        "Kullanıcı Adınız", 
        value=st.session_state.active_username
    ).strip().lower()

    if username_input != st.session_state.active_username:
        st.session_state.active_username = username_input
        st.query_params["user"] = username_input
        st.session_state.messages = []
        st.session_state.GOOGLE_history = []
        st.rerun()

    username = st.session_state.active_username
    
    st.divider()
    st.header("💬 Sohbet Geçmişi")
    
    if st.button("➕ Yeni Sohbet Başlat", use_container_width=True):
        st.session_state.current_chat_id = f"chat_{int(datetime.now().timestamp())}"
        st.session_state.messages = []
        st.session_state.GOOGLE_history = []
        st.rerun()

    chats_ref = db.collection("users").document(username).collection("chats").order_by("created_at", direction=firestore.Query.DESCENDING)
    saved_chats = list(chats_ref.stream())

    chat_titles = {}
    for c in saved_chats:
        data = c.to_dict()
        chat_titles[c.id] = data.get("title", "İsimsiz Sohbet")

    if "current_chat_id" not in st.session_state:
        if saved_chats:
            st.session_state.current_chat_id = saved_chats[0].id
        else:
            st.session_state.current_chat_id = f"chat_{int(datetime.now().timestamp())}"

    for c_id, title in chat_titles.items():
        button_label = f"📌 {title[:25]}" if c_id == st.session_state.current_chat_id else title[:25]
        if st.button(button_label, key=c_id, use_container_width=True):
            st.session_state.current_chat_id = c_id
            st.session_state.messages = []
            st.session_state.GOOGLE_history = []
            st.rerun()

    st.divider()
    st.header("📁 Mühendislik Araçları")
    uploaded_image = st.file_uploader("Görsel Yükle (Devre / Şema)", type=["png", "jpg", "jpeg"])
    if uploaded_image:
        st.image(Image.open(uploaded_image), caption="Yüklenen Görsel", use_container_width=True)

    uploaded_pdf = st.file_uploader("Datasheet Yükle (PDF)", type=["pdf"])
    pdf_text_context = ""
    if uploaded_pdf:
        with st.spinner("PDF taranıyor..."):
            reader = PdfReader(uploaded_pdf)
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    pdf_text_context += text + "\n"
        st.success(f"PDF Yüklendi! ({len(reader.pages)} sayfa)")

# ----------------- 4. SOHBET VERİSİNİ YÜKLEME -----------------
current_chat_ref = db.collection("users").document(username).collection("chats").document(st.session_state.current_chat_id)

if "messages" not in st.session_state or not st.session_state.messages:
    chat_doc = current_chat_ref.get()
    if chat_doc.exists:
        data = chat_doc.to_dict()
        st.session_state.messages = data.get("messages", [])
        st.session_state.GOOGLE_history = []
        for m in st.session_state.messages:
            role = "user" if m["role"] == "user" else "model"
            st.session_state.GOOGLE_history.append(
                types.Content(role=role, parts=[types.Part.from_text(text=m["content"])])
            )
    else:
        st.session_state.messages = []
        st.session_state.GOOGLE_history = []

# ----------------- 5. ANA EKRAN & TALİMATLAR -----------------
st.title("⚡ Elektrik-Elektronik Mühendisi Asistanı (Cloud)")
st.caption(f"Aktif Kullanıcı: **{username}** | Oturum: **{st.session_state.current_chat_id}**")

base_system_instruction = """
Sen kıdemli bir Elektrik-Elektronik Mühendisi teknik asistanısın. 
Görevin sadece ve sadece Elektrik-Elektronik Mühendisliği alanındaki konulara (devre analizi, gömülü sistemler, mikrodenetleyiciler, güç elektroniği, kontrol sistemleri, sinyal işleme, PLC, telekomünikasyon vb.) teknik ve analitik bir yaklaşımla yanıt vermektir.

Kurallar:
1. Yanıtların teknik, formüllere dayalı, mühendislik standartlarına uygun ve analitik olsun.
2. Devre şeması görseli yüklendiyse komponentleri, bağlantı yapısını ve olası hataları adım adım analiz et.
3. PDF/Datasheet yüklendiyse öncelikle oradaki elektriksel parametrelere ve register/pin tablolarına sadık kalarak cevap ver.
4. Elektrik-elektronik mühendisliği alanı dışındaki hiçbir soruya ASLA yanıt verme.
"""

if pdf_text_context:
    effective_instruction = base_system_instruction + f"\n\n[REFERANS DATASHEET / NOT]:\n{pdf_text_context[:40000]}"
else:
    effective_instruction = base_system_instruction

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ----------------- 6. MESAJ İLETİMİ (STREAMING) -----------------
if user_input := st.chat_input("Teknik sorunuzu yazın..."):
    display_text = user_input
    if uploaded_image:
        display_text = f"🖼️ *[Görsel Eklendi]* {user_input}"
    if uploaded_pdf:
        display_text = f"📄 *[Datasheet Aktif]* {display_text}"

    st.session_state.messages.append({"role": "user", "content": display_text})
    with st.chat_message("user"):
        st.markdown(display_text)

    parts = []
    if uploaded_image:
        img_bytes = uploaded_image.getvalue()
        parts.append(types.Part.from_bytes(data=img_bytes, mime_type=uploaded_image.type))
    parts.append(types.Part.from_text(text=user_input))

    st.session_state.GOOGLE_history.append(types.Content(role="user", parts=parts))

    with st.chat_message("assistant"):
        try:
            def stream_generator():
                response_stream = client.models.generate_content_stream(
                    model="GOOGLE-2.0-flash",
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
            
            st.session_state.messages.append({"role": "assistant", "content": full_response})
            st.session_state.GOOGLE_history.append(
                types.Content(role="model", parts=[types.Part.from_text(text=full_response)])
            )

            # Firestore Kaydı
            chat_title = user_input[:30] if len(st.session_state.messages) <= 2 else chat_titles.get(st.session_state.current_chat_id, user_input[:30])
            current_chat_ref.set({
                "title": chat_title,
                "created_at": firestore.SERVER_TIMESTAMP,
                "messages": st.session_state.messages
            }, merge=True)

        except errors.APIError as e:
            st.error(f"Google API Hatası: {e.message}")
        except Exception as e:
            st.error(f"Hata oluştu: {str(e)}")
