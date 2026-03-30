import streamlit as st
import time
import os
import base64
import shutil
import pickle
from io import BytesIO

from typing import List, Optional, Dict
import concurrent.futures
import functools

# Core Backend Imports
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain.chains import create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from duckduckgo_search import DDGS
from googlesearch import search as gsearch
from scholarly import scholarly
from langchain_core.prompts import ChatPromptTemplate


# Voice Imports
import speech_recognition as sr
import pyautogui
from PIL import Image


# --- BACKEND LOGIC ---

class LibraryBackend:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.data_dir = "data"
        self.index_path = os.path.join(self.data_dir, "faiss_index")
        self.embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
        self.vector_store = None
        self.search_wrapper = DDGS()
        self.model_name = "llama-3.3-70b-versatile"

        
        
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
        self._search_cache: Dict[str, List[dict]] = {}
        self._load_vector_store()

    def _load_vector_store(self):
        if os.path.exists(self.index_path):
            try:
                self.vector_store = FAISS.load_local(
                    self.index_path, 
                    self.embeddings, 
                    allow_dangerous_deserialization=True
                )
            except Exception:
                self.vector_store = None

    def set_api_key(self, api_key: str):
        self.api_key = api_key

    # `speak` method removed per request. Voice TTS calls were stripped from UI.

    def listen(self) -> tuple[Optional[str], Optional[str]]:
        """Listen for user command with ultra-high sensitivity calibration."""
        r = sr.Recognizer()
        # Calibrate for much higher sensitivity to capture quiet speech
        r.energy_threshold = 300 
        r.dynamic_energy_threshold = True
        try:
            with sr.Microphone() as source:
                # Optimized noise floor adjustment
                r.adjust_for_ambient_noise(source, duration=0.8)
                # Significantly longer windows for natural human speech
                audio = r.listen(source, timeout=12, phrase_time_limit=15)
                text = r.recognize_google(audio)
                return text, None
        except sr.WaitTimeoutError:
            return None, "Listening timed out. Please speak within 12 seconds."
        except sr.UnknownValueError:
            return None, "Speech was too faint. Try speaking a bit louder or closer to the mic."
        except sr.RequestError:
            return None, "Neural Link (Google API) is unreachable. Check internet."
        except Exception as e:
            return None, f"Hardware Error: {str(e)}"

    def process_pdf(self, file_path: str):
        loader = PyPDFLoader(file_path)
        docs = loader.load()
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        splits = text_splitter.split_documents(docs)
        if self.vector_store is None:
            self.vector_store = FAISS.from_documents(splits, self.embeddings)
        else:
            self.vector_store.add_documents(splits)
        self.vector_store.save_local(self.index_path)

    def search_books(self, query: str, k: int = 3) -> List[dict]:
        if self.vector_store is None: return []
        results = self.vector_store.similarity_search(query, k=k)
        return [{"content": doc.page_content, "metadata": doc.metadata} for doc in results]

    def search_global_books(self, query: str) -> List[dict]:
        """High-speed concurrent search using parallel nodes. Optimized for PDF discovery."""
        if query in self._search_cache: return self._search_cache[query]
        
        # Broaden search to find closest matches without needing author names
        search_query = f"{query} complete book PDF download"
        
        def run_google():
            try:
                g_results = gsearch(search_query, num_results=5, advanced=True)
                return [{"title": r.title, "link": r.url, "snippet": r.description} for r in g_results]
            except: return []

        def run_ddg():
            try:
                # Use DDGS context manager for better connection handling
                with DDGS() as ddgs:
                    results = list(ddgs.text(search_query, max_results=5))
                if not results: return []
                return [{"title": r.get('title', 'Unknown'), "link": r.get('href', '#'), "snippet": r.get('body', '')} for r in results]
            except Exception as e:
                # Silently fail for parallel nodes
                return []


        def run_scholar():
            try:
                search_scholar = scholarly.search_pubs(query)
                results = []
                for _ in range(3):
                    pub = next(search_scholar)
                    results.append({
                        "title": pub['bib'].get('title', 'Academic Reference'),
                        "link": pub.get('pub_url', pub.get('eprint_url', '#')),
                        "snippet": pub['bib'].get('abstract', 'View official publication.')
                    })
                return results
            except: return []

        # Execute all search nodes in parallel for maximum speed
        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = {
                executor.submit(run_google): "google",
                executor.submit(run_ddg): "ddg",
                executor.submit(run_scholar): "scholar"
            }
            
            final_results = []
            for future in concurrent.futures.as_completed(futures):
                res = future.result()
                if res: 
                    final_results.extend(res)
                    break # Return the FASTEST successful node only for speed

        if not final_results:
            return [{"error": "All search nodes are currently offline. Please retry shortly."}]
            
        self._search_cache[query] = final_results
        return final_results

    def chat_with_ai(self, query: str) -> str:
        if not self.api_key: return "API Key missing in System Config."
        try:
            llm = ChatGroq(groq_api_key=self.api_key, model_name=self.model_name)
            response = llm.invoke(query)
            return response.content
        except Exception as e:
            return f"Error: {e}"

    def analyze_reading_context(self, image) -> str:
        """Use Groq vision to scan the screen and provide reading context."""
        if not self.api_key: return "Key missing."
        try:
            # Buffer image to base64
            buffered = BytesIO()
            image.save(buffered, format="JPEG")
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            
            # Using ChatGroq with vision model (llama-3.2-11b-vision)
            # Since LangChain's ChatGroq handles it via standard message structures
            llm = ChatGroq(groq_api_key=self.api_key, model_name="llama-3.2-11b-vision-preview")
            msg = HumanMessage(
                content=[
                    {"type": "text", "text": "As an AI Librarian, describe the book or reading material on my screen. Provide themes and a summary if possible."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_str}"}}
                ]
            )
            response = llm.invoke([msg])

            return response.content
        except Exception as e:
            return f"Vision Error: {e}"


    def ask_library(self, query: str) -> str:
        if not self.api_key: return "API Key missing."
        if self.vector_store is None: return "Archive is empty."
        try:
            llm = ChatGroq(groq_api_key=self.api_key, model_name=self.model_name)
            prompt = ChatPromptTemplate.from_template("""
            You are an advanced AI Librarian. Answer the question based ONLY on the provided archive context:
            <context>
            {context}
            </context>
            Question: {input}""")
            document_chain = create_stuff_documents_chain(llm, prompt)
            retriever = self.vector_store.as_retriever()
            retrieval_chain = create_retrieval_chain(retriever, document_chain)
            response = retrieval_chain.invoke({"input": query})
            return response["answer"]
        except Exception as e:
            return f"RAG Error: {e}"

# --- UI LOGIC ---

st.set_page_config(
    page_title="Myer's Digital Library", 
    page_icon="📚", 
    layout="wide",
    initial_sidebar_state="expanded"
)

if "backend" not in st.session_state:
    st.session_state.backend = LibraryBackend()
if "messages" not in st.session_state:
    st.session_state.messages = []

def get_base64_image(image_path):
    if os.path.exists(image_path):
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    return ""

img_path = r"C:\Users\USER\.gemini\antigravity\brain\d67be4c1-5ba4-407c-8400-2e1dcf0dc87b\library_bg_dark_1773809447534.png"
bg_b64 = get_base64_image(img_path)

st.markdown(f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;700;900&display=swap');
    .stApp {{
        background: linear-gradient(rgba(0, 0, 0, 0.85), rgba(0, 0, 0, 0.85)), url("data:image/png;base64,{bg_b64}");
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
        font-family: 'Outfit', sans-serif;
        color: #FFFFFF;
    }}
    [data-testid="stSidebar"] {{
        background-color: rgba(0, 5, 10, 0.8);
        backdrop-filter: blur(30px);
        border-right: 1px solid rgba(0, 255, 170, 0.15);
    }}
    .glass-card {{
        background: rgba(255, 255, 255, 0.04);
        backdrop-filter: blur(20px);
        border-radius: 24px;
        padding: 35px;
        border: 1px solid rgba(255, 255, 255, 0.1);
        box-shadow: 0 20px 50px 0 rgba(0, 0, 0, 0.7);
        margin-bottom: 30px;
    }}
    .neon-text {{
        color: #00FFAA;
        text-shadow: 0 0 20px rgba(0, 255, 170, 0.7);
        font-weight: 900;
    }}
    .stButton>button {{
        background: linear-gradient(135deg, #00FFAA 0%, #00CCFF 100%);
        color: #000 !important;
        font-weight: 900;
        border-radius: 16px;
        border: none;
        padding: 18px;
        transition: 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
    }}
    .stButton>button:hover {{
        transform: scale(1.05) translateY(-2px);
        box-shadow: 0 10px 30px rgba(0, 255, 170, 0.5);
    }}
    #MainMenu, footer, header {{ visibility: hidden; }}
</style>
""", unsafe_allow_html=True)

# --- SIDEBAR ---
with st.sidebar:
    st.markdown('<h1 class="neon-text" style="font-size: 2.5rem; margin-bottom: 0;">LIBRARIAN OS</h1>', unsafe_allow_html=True)
    st.markdown('<p style="font-size: 0.7rem; opacity: 0.6; margin-bottom: 30px; letter-spacing: 2px;">NEURAL KNOWLEDGE HUB</p>', unsafe_allow_html=True)
    
    navigation = st.radio(
        "NETWORK NODE",
        ["Dashboard", "Neural Ingest", "Universal Search", "Librarian Q&A", "Collective Chat", "Neural Vision"]

    )
    
    st.divider()
    st.markdown('<p style="font-size: 0.9rem; font-weight: 700; color: #00FFAA;">SYSTEM AUTH</p>', unsafe_allow_html=True)
    stored_key = st.text_input("Groq Intelligence Key", type="password", placeholder="Enter Neural Key...", value=st.session_state.get('api_key', ""))
    if stored_key:
        st.session_state.backend.set_api_key(stored_key)
        st.session_state['api_key'] = stored_key
    
    st.divider()
    
    # --- VOICE AGENT BUTTON ---
    if st.button("🎙️ SPEAK"):
        with st.spinner("Librarian is listening..."):
            user_speech, error_msg = st.session_state.backend.listen()
            if user_speech:
                st.toast(f"Captured: '{user_speech}'")
                # Decide mode: RAG or Web
                lower_speech = user_speech.lower()
                if any(word in lower_speech for word in ["search", "find", "global", "look for"]):
                    # Extract book title
                    query = user_speech.lower().replace("search", "").replace("find", "").replace("global", "").replace("look", "").replace("for", "").strip()
                    results = st.session_state.backend.search_global_books(query)
                    if results and "error" not in results[0]:
                        msg = f"I've scanned the global grid for '{query}'. I found {len(results)} potential matches."
                    else:
                        msg = f"I attempted to search the global grid for '{query}', but encountered a system error or no results."
                    
                    # previously: st.session_state.backend.speak(msg)
                    st.session_state.messages.append({"role": "user", "content": f"[Voice] {user_speech}"})
                    st.session_state.messages.append({"role": "assistant", "content": msg})
                    # Also switch to Universal search if possible? Better to keep them in chat.
                else:
                    # Treat as knowledge query
                    response = st.session_state.backend.ask_library(user_speech)
                    # If empty or confused, use general AI
                    if "empty" in response.lower() or "not found" in response.lower():
                        response = st.session_state.backend.chat_with_ai(user_speech)
                    
                    # previously: st.session_state.backend.speak(response)
                    st.session_state.messages.append({"role": "user", "content": f"[Voice] {user_speech}"})
                    st.session_state.messages.append({"role": "assistant", "content": response})
            else:
                st.error(f"Audio Cortex Error: {error_msg}")

    st.markdown(f'<p style="font-size: 0.65rem; opacity: 0.5;">MODEL: {st.session_state.backend.model_name}</p>', unsafe_allow_html=True)

# --- PAGE LOGIC ---

st.markdown('<p style="margin-bottom:-10px; font-weight:400; opacity:0.6; font-size: 0.8rem;">NEURAL SYNC ESTABLISHED // 0xAF92C</p>', unsafe_allow_html=True)

if navigation == "Dashboard":
    st.markdown('<h1 class="neon-text" style="font-size: 5.5rem; line-height: 0.85; margin-bottom: 5px;">LIBRARIAN<br>COLLECTIVE</h1>', unsafe_allow_html=True)
    st.markdown('<p style="font-size: 1.1rem; opacity: 0.8; letter-spacing: 3px; font-weight: 400; color: #00FFAA; text-shadow: 0 0 10px rgba(0, 255, 170, 0.4); margin-bottom: 30px;">BUILT BY MUHAMMAD HADI AND MUHAMMAD HASHAAM</p>', unsafe_allow_html=True)
    st.markdown("""
    <div class="glass-card">
        <h2 class="neon-text">VOICE-ENABLED KNOWLEDGE</h2>
        <p>Your AI Librarian is now active. Use the <b>SPEAK</b> button to interact via natural language. The Librarian can:</p>
        <ul>
            <li>Analyze your private PDF archives with pin-point RAG accuracy.</li>
            <li>Scan the global web for downloadable book PDFs and summaries.</li>
            <li>Answer complex questions using the Llama-3.3 neural cluster.</li>
            <li>Neural Vision: Analyze your screen to understand your active reading context.</li>

        </ul>
    </div>
    """, unsafe_allow_html=True)

elif navigation == "Neural Ingest":
    st.markdown('<h1 class="neon-text">NEURAL INGEST</h1>', unsafe_allow_html=True)
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    upl = st.file_uploader("", type=["pdf"])
    if upl:
        save_p = os.path.join("uploads", upl.name)
        if not os.path.exists("uploads"): os.makedirs("uploads")
        with open(save_p, "wb") as f: f.write(upl.getbuffer())
        with st.spinner("Fragmenting..."):
            st.session_state.backend.process_pdf(save_p)
            st.success("Indexed.")
    st.markdown('</div>', unsafe_allow_html=True)

elif navigation == "Universal Search":
    st.markdown('<h1 class="neon-text">UNIVERSAL GRID</h1>', unsafe_allow_html=True)
    q = st.text_input("QUERY ARCHIVE", placeholder="e.g. Beyond Good and Evil")
    if q:
        res = st.session_state.backend.search_global_books(q)
        if res and "error" in res[0]:
            st.error(f"Archive Search Error: {res[0]['error']}")
        elif not res:
            st.warning("No global matches found for this query.")
        else:
            for r in res:
                st.markdown(f'<div class="glass-card"><h4 class="neon-text">{r["title"]}</h4><p>{r.get("snippet", "")}</p><a href="{r["link"]}" target="_blank" style="color:#000; background:#00FFAA; padding:8px 15px; border-radius:8px; text-decoration:none; font-weight:bold;">DOWNLOAD PDF</a></div>', unsafe_allow_html=True)

elif navigation == "Librarian Q&A":
    st.markdown('<h1 class="neon-text">LIBRARIAN Q&A</h1>', unsafe_allow_html=True)
    st.markdown('<p style="opacity:0.7;">Ask the Librarian about any book ever written. Discover themes, summaries, and historical impact.</p>', unsafe_allow_html=True)
    
    q_query = st.text_input("QUERY THE LIBRARIAN", placeholder="Tell me about 'Crime and Punishment'...")
    if q_query:
        with st.spinner("Accessing Neural Records..."):
            # Use general AI for broad book questions not limited to the indexed archive
            response = st.session_state.backend.chat_with_ai(f"Provide a deep, expert-level summary and analysis of the book: {q_query}")
            st.markdown(f'<div class="glass-card"><h3 class="neon-text">CHOSEN VOLUME: {q_query.upper()}</h3>{response}</div>', unsafe_allow_html=True)

elif navigation == "Collective Chat":
    st.markdown('<h1 class="neon-text">SYSTEM CHAT</h1>', unsafe_allow_html=True)
    for m in st.session_state.messages:
        with st.chat_message(m["role"]): st.markdown(m["content"])
    if p := st.chat_input("Input..."):
        st.session_state.messages.append({"role": "user", "content": p})
        with st.chat_message("assistant"):
            resp = st.session_state.backend.ask_library(p)
            st.markdown(resp)
            st.session_state.messages.append({"role": "assistant", "content": resp})

elif navigation == "Neural Vision":
    st.markdown('<h1 class="neon-text">NEURAL VISION</h1>', unsafe_allow_html=True)
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    if st.button("👁️ SCAN SCREEN"):
        with st.spinner("Analyzing active screen..."):
            # Capture screen
            screenshot = pyautogui.screenshot()
            # Since I don't have a vision model configured in this simple backend yet,
            # I'll simulate or add a simple call to Groq Vision if possible
            vision_analysis = st.session_state.backend.analyze_reading_context(screenshot)
            st.markdown(f'<div class="neon-text">VISION REPORT</div>\n{vision_analysis}', unsafe_allow_html=True)
            # previously: st.session_state.backend.speak(vision_analysis)
    st.markdown('</div>', unsafe_allow_html=True)


st.sidebar.markdown('<p style="position: fixed; bottom: 20px; font-size: 0.6rem; opacity: 0.4;">OS STATUS: SECURE</p>', unsafe_allow_html=True)

