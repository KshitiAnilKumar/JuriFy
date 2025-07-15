import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import speech_recognition as sr
import sounddevice as sd
import numpy as np
import wave
import tempfile
import os
import base64
import json
import mysql.connector
from deep_translator import GoogleTranslator
from datetime import datetime
import hashlib

st.set_page_config(page_title="JuriFy", layout="wide")  
    
def generate_pdf_hash(file_bytes):
    return hashlib.sha256(file_bytes).hexdigest()

CHAT_HISTORY_DIR = "chat_history"
os.makedirs(CHAT_HISTORY_DIR, exist_ok=True)

def get_user_sessions(username):
    sessions = []
    for file in os.listdir(CHAT_HISTORY_DIR):
        if file.startswith(f"{username}_session") and file.endswith(".json"):
            session_id = file.replace(f"{username}_session", "").replace(".json", "")
            sessions.append(int(session_id))
    return sorted(sessions)

def get_chat_history_path(username, pdf_filename):
    return os.path.join(CHAT_HISTORY_DIR, f"{username}_{pdf_filename}.json")

def save_chat_history(username, pdf_filename, chat_log):
    with open(get_chat_history_path(username, pdf_filename), "w") as file:
        json.dump(chat_log, file)

def load_chat_history(username, pdf_filename):
    path = get_chat_history_path(username, pdf_filename)
    if os.path.exists(path):
        with open(path, "r") as file:
            return json.load(file)
    return []

GENAI_API_KEY = "PUT_YOUR_GENAI_API_KEY_HERE"

if not GENAI_API_KEY:
    st.error("GENAI_API_KEY is missing. Please add your key directly in the code.")
    st.stop()

# ✅ Configure Gemini with the key
genai.configure(api_key=GENAI_API_KEY.strip())

# ✅ Direct MySQL Configuration (no .env)
MYSQL_CONFIG = {
    'user': 'PUT_YOUR_MYSQL_USERNAME_HERE',
    'password': 'PUT_YOUR_MYSQL_PASSWORD_HERE',
    'host': 'PUT_YOUR_MYSQL_HOST_HERE',
    'port': 3306,
    'database': 'PUT_YOUR_DATABASE_NAME_HERE'
}

def get_db_connection():
    return mysql.connector.connect(**MYSQL_CONFIG)

def save_full_session_to_db(username, password, pdf_filename, chat_log):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        questions_answers = json.dumps(chat_log)

        query = """
            INSERT INTO chat_session (username, password, pdf_filename, start_time, questions_answers)
            VALUES (%s, %s, %s, %s, %s)
        """
        cursor.execute(query, (username, password, pdf_filename, start_time, questions_answers))

        conn.commit()
        cursor.close()
        conn.close()
    except mysql.connector.Error as err:
        st.error(f"Database Error while saving session: {err}")

# ✅ Save full session
def save_full_session_to_db(username, password, pdf_filename, chat_log):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        questions_answers = json.dumps(chat_log)

        query = """
            INSERT INTO chat_session (username, password, pdf_filename, start_time, questions_answers)
            VALUES (%s, %s, %s, %s, %s)
        """
        cursor.execute(query, (username, password, pdf_filename, start_time, questions_answers))
        conn.commit()
        cursor.close()
        conn.close()
    except mysql.connector.Error as err:
        st.error(f"Database Error while saving session: {err}")

# ✅ Save single chat entry
def save_chat_to_db(username, question, answer):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO chats (username, question, answer) VALUES (%s, %s, %s)", (username, question, answer))
        conn.commit()
        cursor.close()
        conn.close()
    except mysql.connector.Error as err:
        st.error(f"Database Error: {err}")

# ✅ Handle local credential saving (not used in cloud)
CREDENTIALS_FILE = "credentials.json"

def load_credentials():
    if os.path.exists(CREDENTIALS_FILE):
        with open(CREDENTIALS_FILE, "r") as file:
            return json.load(file)
    return {}

def save_credentials(username, password):
    credentials = load_credentials()
    credentials[username] = password
    with open(CREDENTIALS_FILE, "w") as file:
        json.dump(credentials, file)


# PDF text extraction
def extract_text_from_pdf(file_bytes):
    text = ""
    with fitz.open(stream=file_bytes, filetype="pdf") as doc:
        for page in doc:
            text += page.get_text("text") + "\n\n"
    return text

# Preview single scrollable PDF view
def preview_pdf_scrollable(uploaded_file):
    base64_pdf = base64.b64encode(uploaded_file.read()).decode('utf-8')
    pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="600px" type="application/pdf"></iframe>'
    st.markdown(pdf_display, unsafe_allow_html=True)

# High Court file check
def is_valid_high_court_case(text):
    keywords = [
        "High Court of Karnataka",
        "Karnataka High Court",
        "IN THE HIGH COURT OF KARNATAKA",
        "IN THE HON'BLE HIGH COURT OF KARNATAKA",
        "Bengaluru Bench",
        "Dharwad Bench",
        "Kalaburagi Bench"
    ]
    return any(keyword.lower() in text.lower() for keyword in keywords)

# Chat with Gemini
def chat_with_ai(user_query, context=""):
    model = genai.GenerativeModel("gemini-1.5-flash")

    instruction = (
        "You are JuriFy, a legal assistant focused on Indian judiciary only. "
        "You must ONLY answer questions that relate directly to the uploaded court document. "
        "If a user asks anything outside the uploaded case, say: "
        "'⚠️ I can only respond to queries directly related to the uploaded Indian court judgment.' "
        "Do not answer general legal questions, foreign law, or anything beyond this document. "
        "Interpret even casual or vague questions based on the document's content as best as you can."
    )

    # Optional: show past interactions to maintain context
    past_qas = "\n".join([f"Q: {x['question']}\nA: {x['answer']}" for x in st.session_state.chat_log])

    prompt = f"{instruction}\n\nUploaded Case Context:\n{context}\n\nPrevious Q&A:\n{past_qas}\n\nNew Question: {user_query}\nAnswer:"

    response = model.generate_content(prompt)
    return response.text

# Audio recording
def record_audio_to_file():
    temp_audio_path = tempfile.NamedTemporaryFile(delete=False, suffix=".wav").name
    fs = 44100
    duration = 10
    st.info("🎙 Recording for 10 seconds... Speak now!")
    audio_data = sd.rec(int(duration * fs), samplerate=fs, channels=1, dtype=np.int16)
    sd.wait()
    with wave.open(temp_audio_path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(fs)
        wf.writeframes(audio_data.tobytes())
    st.success("✅ Recording completed!")
    return temp_audio_path

lang_code_map = {
    "English": "en-US", "Hindi": "hi-IN", "Bengali": "bn-IN", "Telugu": "te-IN", "Marathi": "mr-IN",
    "Tamil": "ta-IN", "Urdu": "ur-IN", "Gujarati": "gu-IN", "Malayalam": "ml-IN",
    "Kannada": "kn-IN", "Odia": "or-IN", "Punjabi": "pa-IN", "Assamese": "as-IN",
    "Maithili": "hi-IN", "Santali": "hi-IN", "Kashmiri": "hi-IN", "Konkani": "hi-IN",
    "Sindhi": "hi-IN", "Nepali": "ne-NP", "Manipuri": "hi-IN", "Bodo": "hi-IN",
    "Dogri": "hi-IN", "Sanskrit": "hi-IN", "Tulu": "hi-IN"
}

def recognize_and_translate(audio_path, target_language):
    recognizer = sr.Recognizer()
    with sr.AudioFile(audio_path) as source:
        audio = recognizer.record(source)
    try:
        text = recognizer.recognize_google(audio, language=lang_code_map.get(target_language, "en-US"))
        return text
    except:
        return "Could not transcribe."

def login():
    st.title("Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    USER_CREDENTIALS = load_credentials()

    if st.button("Login"):
        if USER_CREDENTIALS.get(username) == password:
            st.session_state.logged_in = True
            st.session_state.username = username
            st.session_state.password = password
            st.session_state.page = "main"
            st.session_state.sessions = get_user_sessions(username)
            st.session_state.chat_log = []
            st.rerun()
        else:
            st.error("❌ Incorrect username or password")

    if st.button("New User? Register"):
        st.session_state.show_login = False
        st.rerun()

    if st.button("⬅ Back to Home Page"):
        st.session_state.show_login = None
        st.rerun()


def register():
    st.title("📝 Register")
    username = st.text_input("Choose a Username")
    password = st.text_input("Choose a Password", type="password")
    confirm = st.text_input("Confirm Password", type="password")

    if st.button("Register"):
        if username in load_credentials():
            st.error("Username already exists.")
        elif password != confirm:
            st.error("Passwords do not match.")
        else:
            save_credentials(username, password)
            st.success("Registration successful. Please login.")
            st.session_state.show_login = True
            st.rerun()
            
def summarize_document(prompt, document_text):
    model = genai.GenerativeModel("gemini-1.5-flash")
    response = model.generate_content(f"{prompt}\n\n{document_text}")
    return response.text
    
def is_valid_indian_court_case(text):
    keywords = [
        "Supreme Court of India", "IN THE SUPREME COURT OF INDIA",
        "High Court", "IN THE HIGH COURT OF",
        "District Court", "IN THE DISTRICT COURT"
    ]
    states = [
        "Andhra Pradesh", "Assam", "Bihar", "Chhattisgarh", "Delhi", "Goa", "Gujarat",
        "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh",
        "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab",
        "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh",
        "Uttarakhand", "West Bengal", "Chandigarh", "Puducherry"
    ]
    text_lower = text.lower()
    return (
        any(k.lower() in text_lower for k in keywords)
        and any(state.lower() in text_lower for state in states)
    )

def summary_page():
    st.title("📄 JuriFy")
    left, right = st.columns([1, 2])

    with left:
        uploaded_file = st.file_uploader("📂 Upload a PDF File", type="pdf")
        if uploaded_file:
            st.write("### PDF Preview")
            preview_pdf_scrollable(uploaded_file)
            st.session_state.uploaded_file = uploaded_file
            st.session_state.pdf_filename = uploaded_file.name

    with right:
        uploaded_file = st.session_state.get("uploaded_file")
        if uploaded_file:
            st.session_state.uploaded_file = uploaded_file
            st.session_state.pdf_filename = uploaded_file.name 
            uploaded_file.seek(0)
            file_bytes = uploaded_file.read()
            st.session_state.pdf_filename = uploaded_file.name  # ✅ Store filename
            st.session_state.text = extract_text_from_pdf(file_bytes)
            st.session_state.active_pdf_text = st.session_state.text
            st.session_state.active_pdf_name = st.session_state.pdf_filename
            
            if not is_valid_indian_court_case(st.session_state.text):
                st.error("🚫 Only Supreme, High, or District Court cases from India are allowed.")
                return
                
            st.write("### Summary")
            summary = summarize_document("Summarize this Karnataka High Court legal document clearly and briefly.", st.session_state.text)
            st.write(summary)
            
            st.write("### Key Insights")
            insights = summarize_document("Provide key legal insights and findings from this Karnataka High Court judgment.", st.session_state.text)
            st.write(insights)


            translate_target = st.selectbox("Translate Summary & Key Insights To", list(lang_code_map.keys()))
            if st.button("Translate"):
                lang_code = lang_code_map.get(translate_target, 'en')[:2]
                translated_summary = GoogleTranslator(source='auto', target=lang_code).translate(summary)
                translated_insights = GoogleTranslator(source='auto', target=lang_code).translate(insights)
                st.write("#### Translated Summary")
                st.write(translated_summary)
                st.write("#### Translated Key Insights")
                st.write(translated_insights)


            if st.button("➡ Q&A ChatBot"):
                # Reset state for the new PDF session
                st.session_state.page = "chat"
                st.session_state.messages = []
                st.session_state.chat_log = []
                st.rerun()

            if "current_question" not in st.session_state:
                st.session_state.current_question = ""
            if "current_response" not in st.session_state:
                st.session_state.current_response = ""
                

def home_page():
    st.markdown("""
    <style>
    .header-container {
        display: flex;
        align-items: center;
        justify-content: flex-start;
        padding: 20px 40px 10px;
        background-color: #f8f9fa;
        border-bottom: 1px solid #e0e0e0;
    }

    .header-title {
        font-size: 2rem;
        font-weight: 700;
        color: #1a237e;
        margin: 10;
    }
    </style>

  <div class="header-container">
        <div class="header-title">JuriFy</div>
    </div>
  """, unsafe_allow_html=True)

    st.markdown("""
    <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700&display=swap" rel="stylesheet">
    
    <style>
      .welcome-banner {
        background-color: #1a237e;  /* Deep Blue */
        color: white;
        text-align: center;
        padding: 100px 60px;
        border-radius: 16px;
        margin: 120px 100px;
        box-shadow: 0 12px 32px rgba(0, 0, 0, 0.15);
      }
    
      .welcome-banner h1, .welcome-banner p {
        font-family: 'Playfair Display', serif;
      }
    
      .welcome-banner h1 {
        font-size: 4rem;
        font-weight: 700;
        margin: 0;
      }
    
      .welcome-banner p {
        font-size: 1.5rem;
        font-weight: 400;
        margin-top: 20px;
        opacity: 0.9;
      }
    </style>
    
    <div class="welcome-banner">
      <h1>Welcome to JuriFy</h1>
      <p>Read Less, Understand More — Decode law in seconds, not hours.</p>
    </div>
    """, unsafe_allow_html=True)


    st.markdown("""
    <style>
      .hero {
        padding: 40px; /* reduced padding to match below */
        margin-left: 40px; /* aligns with the content below */
        margin-right: 40px;
      }
    
      .hero-text h1 {
        font-size: 3rem;
        color: #1a237e;
        margin-bottom: 20px;
      }
    
      .hero-text p {
        font-size: 1.2rem;
        color: #333;
        line-height: 1.7;
        margin-bottom: 30px;
      }
    
      .section-pair {
        display: flex;
        justify-content: space-between;
        gap: 60px;
        flex-wrap: wrap;
        margin: 60px 40px;
      }
    
      .section {
        flex: 1;
        min-width: 300px;
      }
    
      .section h2 {
        font-size: 1.8rem;
        color: #1a237e;
        margin-bottom: 16px;
      }
    
      .section ul {
        padding-left: 20px;
        line-height: 1.7;
        color: #444;
      }
    </style>
    
    <div class="hero">
      <div class="hero-text">
        <h1>JuriFy: Legal Case Summarizer</h1>
        <p>
          Tired of decoding complex court rulings? JuriFy turns dense Indian legal judgments into clear, clutch summaries you can actually understand. Whether  you're prepping for moot court, reviewing case law, or just need answers fast, JuriFy delivers instant highlights, insights, and chat-ready takeaways — no legal degree required. One upload, one click, one PDF at a time — we make justice make sense.
        </p>
      </div>
    </div>
    """, unsafe_allow_html=True)

    

    st.markdown("<br>", unsafe_allow_html=True)  # spacing below the paragraph
    button_col1, button_col2 = st.columns([1, 1])
    
    with button_col1:
        if st.button("Login", key="login_button", use_container_width=True):
            st.session_state.show_login = True
            st.rerun()
    with button_col2:
        if st.button("Register", key="register_button", use_container_width=True):
            st.session_state.show_login = False
            st.rerun()

    # Two-column layout for features
    st.markdown("""
    <div class="section-pair">
      <div class="section" id="who">
        <h2>Who is this tool for?</h2>
        <ul>
          <li>Law students preparing for moot court or internships</li>
          <li>Advocates reviewing judgments and drafting briefs</li>
          <li>Paralegals summarizing case files for clients</li>
          <li>Researchers exploring legal precedents quickly</li>
          <li>Citizens seeking clarity on their court orders</li>
        </ul>
      </div>

      <div class="section" id="how-to">
        <h2>How to Use JuriFy</h2>
        <ul>
          <li>Login or register to your secure workspace</li>
          <li>Upload a PDF of a Supreme, High, or District Court judgment</li>
          <li>Receive instant summaries, insights, and case context</li>
          <li>Use the chatbot to ask any follow-up questions</li>
          <li>Translate or export findings in a click</li>
        </ul>
      </div>
    </div>
    """, unsafe_allow_html=True)

def get_next_session_index(username, chat_history_dir="chat_history"):
    existing_files = [
        f for f in os.listdir(chat_history_dir)
        if f.startswith(f"{username}_session") and f.endswith(".json")
    ]
    indices = [
        int(f.split("_session")[1].split(".json")[0])
        for f in existing_files if "_session" in f
    ]
    return max(indices, default=0) + 1

def get_next_session_index(username, chat_history_dir="chat_history"):
    existing_files = [
        f for f in os.listdir(chat_history_dir)
        if f.startswith(f"{username}_session") and f.endswith(".json")
    ]
    indices = [
        int(f.split("_session")[1].split(".json")[0])
        for f in existing_files if "_session" in f
    ]
    return max(indices, default=0) + 1

def chat_page():
    st.title("Jurify Q&A")

    with st.sidebar:
        st.title("Menu")
        if st.button("Back to Summary Page"):
            st.session_state.page = "main"
            st.rerun()
        if st.button("Exit"):
            keys_to_clear = [
                "logged_in", "uploaded_file", "pdf_filename", "text",
                "active_pdf_text", "active_pdf_name", "chat_log",
                "chat_log", "messages", "current_question", "current_response",
                "sessions"
            ]
            for key in keys_to_clear:
                if key in st.session_state:
                    del st.session_state[key]
            st.session_state.show_login = True
            st.session_state.page = "main"
            st.success("Logged out successfully.")
            st.rerun()

        if "chat_log" not in st.session_state:
            st.session_state.chat_log = []
        if "messages" not in st.session_state:
            st.session_state.messages = []

        if "active_pdf_name" not in st.session_state or not st.session_state.get("active_pdf_name"):
            st.warning("Please upload a PDF from the Summary page to start a new session.")
            return

        existing_sessions = [
            f.replace(f"{st.session_state.username}_", "").replace(".json", "")
            for f in os.listdir(CHAT_HISTORY_DIR)
            if f.startswith(f"{st.session_state.username}_") and f.endswith(".json")
        ]

        if st.session_state.active_pdf_name not in existing_sessions:
            existing_sessions.append(st.session_state.active_pdf_name)

        selected_pdf = st.sidebar.radio("Choose PDF Session", sorted(existing_sessions))

        st.markdown('''
        <script>
        const dropdowns = window.parent.document.querySelectorAll('select');
        for (const dropdown of dropdowns) {
            if (dropdown.name.includes("session_picker")) {
                dropdown.size = dropdown.options.length;
                dropdown.focus();
            }
        }
        </script>
        ''', unsafe_allow_html=True)


        if selected_pdf:
            st.session_state.pdf_filename = selected_pdf
        
            # ✅ Block to ensure only active PDF can be used for Q&A
            pdf_filename = st.session_state.get("pdf_filename")
            
            if not pdf_filename:
                st.warning("No PDF selected. Please upload a PDF from the Summary page.")
                return
        
            if pdf_filename != st.session_state.get("active_pdf_name"):
                st.warning("⚠️ The selected PDF is not the one currently uploaded in the Summary Page. Please go back and re-upload it.")
                return
        
            # ✅ Load history & messages only if active PDF matches
            st.session_state.chat_log = load_chat_history(st.session_state.username, selected_pdf)
        
            st.session_state.messages = []
            for item in st.session_state.chat_log:
                question_text = item["question"].split(" (")[0]
                st.session_state.messages.append({"role": "user", "content": question_text})
                st.session_state.messages.append({"role": "assistant", "content": item["answer"]})


    # Remove this redundant line if already loading based on `selected_pdf`
    # But if you want to reload using current filename separately, then keep it
    st.session_state.chat_log = load_chat_history(st.session_state.username, st.session_state.pdf_filename)

    left_col, right_col = st.columns([2, 1])

    with left_col:
        st.markdown("### 💬 Ask Your Question")

        selected_lang = st.selectbox("Select Language", list(lang_code_map.keys()), key="multi_lang")
        target_lang_code = lang_code_map.get(selected_lang, "en-US")[:2]

        if "messages" not in st.session_state:
            st.session_state.messages = []

        chat_container = st.container()
        with chat_container:
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

        user_query = ""

        # 🎙 Voice Input
        if st.button("🎙 Record Voice"):
            audio_path = record_audio_to_file()
            user_query = recognize_and_translate(audio_path, selected_lang)

        # Text input fallback
        typed_input = st.chat_input("💬 Ask a question about the PDF:")
        if typed_input:
            user_query = typed_input

        if user_query:
            st.session_state.current_question = user_query
            st.session_state.messages.append({"role": "user", "content": user_query})
            with chat_container:
                with st.chat_message("user"):
                    st.markdown(user_query)

            context = st.session_state.get("text", "")
            ai_response = chat_with_ai(user_query, context)
            translated_response = GoogleTranslator(source='auto', target=target_lang_code).translate(ai_response)
            st.session_state.current_response = translated_response

            st.session_state.messages.append({"role": "assistant", "content": translated_response})
            st.session_state.chat_log.append({
                "question": f"{user_query} ({selected_lang})",
                "answer": translated_response
            })

            with chat_container:
                with st.chat_message("assistant"):
                    st.markdown(translated_response)

        save_full_session_to_db(
            st.session_state.username,
            st.session_state.password,
            st.session_state.pdf_filename,  # use PDF filename as session_id for clarity
            st.session_state.chat_log
        )
    save_chat_history(
        st.session_state.username,
        st.session_state.pdf_filename,
        st.session_state.chat_log
    )

    with right_col:
        st.markdown("### Session Chat History")
        if st.session_state.chat_log:
            with st.expander("🗨 Chat History", expanded=True):
                for entry in st.session_state.chat_log:
                    st.markdown(f"**You:** {entry['question']}")
                    st.markdown(f"**AI:** {entry['answer']}")



    save_chat_history(st.session_state.username, st.session_state.pdf_filename, st.session_state.chat_log)

# App Controller
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "show_login" not in st.session_state:
    st.session_state.show_login = None
if "page" not in st.session_state:
    st.session_state.page = "main"

# 🔄 Route based on login/register/home status
if st.session_state.logged_in:
    if st.session_state.page == "main":
        summary_page()
    elif st.session_state.page == "chat":
        chat_page()
elif st.session_state.show_login is True:
    login()
elif st.session_state.show_login is False:
    register()
else:
    home_page()
