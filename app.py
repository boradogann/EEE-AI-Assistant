import streamlit as st
import os
import json
import hashlib
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

# Sayfa kaymasını engelleyen stil
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

# ----------------- 2. GEMINI CLIENT -----------------
api_key = os.environ.get("GOOGLE_API_KEY")
if not api_key:
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = str(st.secrets["GOOGLE_API_KEY"]).strip()
    else:
        st.error("GOOGLE_API_KEY bulunamadı. Lütfen Streamlit Secrets alanına tanımlayın.")
        st.stop()

client = genai.Client(api_key=api_key)

# ----------------- 3. KULLANICI DOĞRULAMA (AUTH) FONKSİYONLARI -----------------
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

if "logged_in_user" not in st.session_state:
    st.session_state.logged_in_user = None

# GİRİŞ YAPILMAMIŞSA GİRİŞ / KAYIT EKRANI GÖSTER
if not st.session_state.logged_in_user:
    st.title("⚡ EE Asistanı - Giriş Paneli")
    
    auth_tab1, auth_tab2 = st.tabs(["🔑 Giriş Yap", "📝 Kayıt Ol"])
    
    with auth_tab1:
        st.subheader("Oturum Aç")
        login_user = st.text_input("Kullanıcı Adı", key="login_u").strip().lower()
        login_pass = st.text_input("Şifre", type="password", key="login_p")
        
        if st.button("Giriş Yap", use_container_width=True, type="primary"):
            if not login_user or not login_pass:
                st.warning("Lütfen kullanıcı adı ve şifrenizi girin.")
            else:
                user_doc = db.collection("users").document(login_user).get()
                if user_doc.exists:
                    stored_hash = user_doc.to_dict().get("password_hash")
                    if stored_hash == hash_password(login_pass):
                        st.session_state.logged_in_user = login_user
                        st.success("Giriş başarılı!")
                        st.rerun()
                    else:
                        st.error("Hatalı şifre girdiniz.")
                else:
                    st.error("Bu kullanıcı adı bulunamadı. Lütfen kayıt olun.")

    with auth_tab2:
        st.subheader("Yeni Hesap Oluştur")
        reg_user = st.text_input("Kullanıcı Adı Seçin", key="reg_u").strip().lower()
        reg_pass = st.text_input("Şifre Belirleyin", type="password", key="reg_p")
        reg_pass_confirm = st.text_input("Şifre Tekrar", type="password", key="reg_pc")
        
        if st.button("Kayıt Ol", use_container_width=True):
            if not reg_user or not reg_pass:
                st.warning("Alanlar boş bırakılamaz.")
            elif reg_pass != reg_pass_confirm:
                st.error("Şifreler birbiriyle eşleşmiyor.")
            elif len(reg_pass) < 4:
                st.warning("Şifre en az 4 karakter olmalıdır.")
            else:
                user_ref = db.collection("users").document(reg_user)
                if user_ref.get().exists:
                    st.error("Bu kullanıcı adı zaten alınmış. Farklı bir isim seçin.")
                else:
                    user_ref.set({
                        "username": reg_user,
                        "password_hash": hash_password(reg_pass),
                        "created_at": firestore.SERVER_TIMESTAMP
                    })
                    st.session_state.logged_in_user = reg_user
                    st.success("Hesap başarıyla oluşturuldu!")
                    st.rerun()
    st.stop()

# ----------------- 4. OTURUM AÇILDIKTAN SONRAKİ SIDEBAR -----------------
username = st.session_state.logged_in_user

with st.sidebar:
    st.header(f"👤 {username.capitalize()}")
    if st.button("🚪 Çıkış Yap", use_container_width=True):
        st.session_state.logged_in_user = None
        if "current_chat_id" in st.session_state:
            del st.session_state["current_chat_id"]
        if "messages" in st.session_state:
            del st.session_state["messages"]
        st.rerun()

    st.divider()
    st.header("💬 Sohbet Geçmişi")
    
    if st.button("➕ Yeni Sohbet Başlat", use_container_width=True):
        st.session_state.current_chat_id = f"chat_{int(datetime.now().timestamp())}"
        st.session_state.messages = []
        st.rerun()

    # Firestore'dan sadece bu kullanıcının sohbetlerini çek
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

    # Sohbetler ve Silme Butonu
    for c_id, title in chat_titles.items():
        col1, col2 = st.columns([0.8, 0.2])
        button_label = f"📌 {title[:20]}" if c_id == st.session_state.current_chat_id else title[:20]
        
        with col1:
            if st.button(button_label, key=f"btn_{c_id}", use_container_width=True):
                st.session_state.current_chat_id = c_id
                if "messages" in st.session_state:
                    del st.session_state["messages"]
                st.rerun()
        with col2:
            if st.button("🗑️", key=f"del_{c_id}", help="Bu sohbeti sil"):
                db.collection("users").document(username).collection("chats").document(c_id).delete()
                if st.session_state.current_chat_id == c_id:
                    if "current_chat_id" in st.session_state:
                        del st.session_state["current_chat_id"]
                    if "messages" in st.session_state:
                        del st.session_state["messages"]
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

# ----------------- 5. SOHBET VERİSİNİ YÜKLEME -----------------
current_chat_ref = db.collection("users").document(username).collection("chats").document(st.session_state.current_chat_id)

if "messages" not in st.session_state or st.session_state.messages is None:
    chat_doc = current_chat_ref.get()
    if chat_doc.exists:
        data = chat_doc.to_dict()
        st.session_state.messages = data.get("messages", [])
    else:
        st.session_state.messages = []

# ----------------- 6. ANA EKRAN & TALİMATLAR -----------------
st.title("⚡ Elektrik-Elektronik Mühendisi Asistanı")
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
    effective_instruction = base_system_instruction + f"\n\n[REFERANS DATASHEET / NOT]:\n{pdf_text_context[:25000]}"
else:
    effective_instruction = base_system_instruction

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ----------------- 7. MESAJ İLETİMİ VE AKIŞ -----------------
if user_input := st.chat_input("Teknik sorunuzu yazın..."):
    display_text = user_input
    if uploaded_image:
        display_text = f"🖼️ *[Görsel Eklendi]* {user_input}"
    if uploaded_pdf:
        display_text = f"📄 *[Datasheet Aktif]* {display_text}"

    with st.chat_message("user"):
        st.markdown(display_text)

    # API için son 6 mesajlık pencere oluştur (Hız optimizasyonu)
    gemini_contents = []
    last_role = None
    recent_messages = st.session_state.messages[-6:]
    for msg in recent_messages:
        r = "user" if msg["role"] == "user" else "model"
        if r != last_role:
            gemini_contents.append(types.Content(role=r, parts=[types.Part.from_text(text=msg["content"])]))
            last_role = r

    current_parts = []
    if uploaded_image:
        current_parts.append(types.Part.from_bytes(data=uploaded_image.getvalue(), mime_type=uploaded_image.type))
    current_parts.append(types.Part.from_text(text=user_input))

    if last_role == "user" and len(gemini_contents) > 0:
        gemini_contents.pop()
        
    gemini_contents.append(types.Content(role="user", parts=current_parts))

    with st.chat_message("assistant"):
        try:
            response_stream = client.models.generate_content_stream(
                model="gemini-3.6-flash",
                contents=gemini_contents,
                config=types.GenerateContentConfig(
                    system_instruction=effective_instruction,
                    temperature=0.2,
                )
            )

            def stream_wrapper():
                for chunk in response_stream:
                    if chunk.text:
                        yield chunk.text

            full_response = st.write_stream(stream_wrapper())

            st.session_state.messages.append({"role": "user", "content": display_text})
            st.session_state.messages.append({"role": "assistant", "content": full_response})

            chat_title = user_input[:30] if len(st.session_state.messages) <= 2 else chat_titles.get(st.session_state.current_chat_id, user_input[:30])
            current_chat_ref.set({
                "title": chat_title,
                "created_at": firestore.SERVER_TIMESTAMP,
                "messages": st.session_state.messages
            }, merge=True)

        except errors.APIError as e:
            st.error(f"Google API Hatası ({e.code}): {e.message}")
        except Exception as e:
            st.error(f"Sistem Hatası: {str(e)}")
