import streamlit as st
import re
from pathlib import Path
import time
from datetime import datetime
from publications_search import PublicationChatbot
import os
import subprocess

# ----------------------------
# Page configuration
# ----------------------------
st.set_page_config(
    page_title="DUK ScholarSearch",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------------------
# Styles (dark blue theme + big headers)
# ----------------------------
st.markdown("""
<style>
.main-header{
  font-size:2.6rem; font-weight:800; color:#1E3A8A; text-align:center;
  padding:1rem; background:linear-gradient(90deg,#EFF6FF 0%,#DBEAFE 100%); border-radius:10px; margin-bottom:1rem;
}
.sub-header{
  font-size:1.3rem; font-weight:600; color:#1F2937; text-align:center; margin-bottom:1.2rem;
}
.stButton>button{
  width:100%; background-color:#1E3A8A; color:white; font-weight:700;
  border-radius:8px; padding:0.55rem 1rem; border:none;
}
.stButton>button:hover{ background-color:#1E40AF; }
div[data-testid="stSidebar"] .stButton>button{
  background-color:#1E3A8A; color:white; font-weight:700;
}
div[data-testid="stSidebar"] .stButton>button:hover{ background-color:#1E40AF; }
.publication-card{ background-color:#F9FAFB; padding:1rem; border-radius:8px; border-left:4px solid #1E3A8A; margin-bottom:1rem;}
.stats-box{ background-color:#EFF6FF; padding:1rem; border-radius:8px; text-align:center; border:2px solid #DBEAFE; }
</style>
""", unsafe_allow_html=True)

# ----------------------------
# Paths and constants
# ----------------------------
PUBLICATIONS_FOLDER = "publications"
FACULTY_LISTS_FILE = "faculty_list.md"
MAIN_PUBLICATIONS_FILE = "publications/2025.md"

# ----------------------------
# Ensure directories
# ----------------------------
os.makedirs(PUBLICATIONS_FOLDER, exist_ok=True)

# ----------------------------
# Session state
# ----------------------------
if 'chatbot' not in st.session_state:
    with st.spinner("🔄 Initializing publication search system..."):
        st.session_state.chatbot = PublicationChatbot(PUBLICATIONS_FOLDER, FACULTY_LISTS_FILE)
    st.session_state.chat_history = []
    st.session_state.current_query = ""
    st.session_state.role = "guest"
    st.session_state.publications_input = ""
    st.session_state.source_input = ""
    st.session_state.clear_inputs = False

# ----------------------------
# Header
# ----------------------------
st.markdown('<div class="main-header">📚 DUK ScholarSearch: Fast Publication Discovery</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Search publications</div>', unsafe_allow_html=True)

# ----------------------------
# Helpers
# ----------------------------
schools = {
    "SoDS": "School of Digital Sciences",
    "SoCSE": "School of Computer Science and Engineering",
    "SoESA": "School of Electronic Systems and Automation",
    "SoI": "School of Informatics",
    "SoDiHLA": "School of Digital Humanities and Liberal Arts"
}
school_aliases = { **{k.lower(): k for k in schools.keys()}, **{v.lower(): k for k, v in schools.items()} }

def is_school_query(text: str):
    t = (text or "").strip().lower()
    m = re.search(r'faculty(?:\s+members)?\s+of\s+(.+)$', t) or re.search(r'members\s+of\s+(.+)$', t)
    if m:
        tail = re.sub(r'[^a-z\s]', ' ', m.group(1).strip())
        tail = re.sub(r'\s+', ' ', tail).strip()
        if tail in school_aliases: return school_aliases[tail]
        for code in schools.keys():
            if tail == code.lower() or code.lower() in tail: return code
        for code, fullname in schools.items():
            if fullname.lower() in tail: return code
    return None

def is_plain_name_query(text: str):
    t = (text or "").strip()
    if not t or re.search(r'\bfaculty\b|\bmembers?\s+of\b', t, flags=re.IGNORECASE) or len(t) > 80: return None
    tokens = re.split(r'\s+', t)
    if len(tokens) == 0 or len(tokens) > 6: return None
    if not any(re.search(r'[A-Za-z]', tok) for tok in tokens): return None
    return t

def route_query(q: str) -> str:
    q = (q or "").strip()
    if not q: return ""
    sc = is_school_query(q)
    if sc: return f"Publications of faculty members of {sc}"
    nm = is_plain_name_query(q)
    if nm: return f"Publications of {nm}"
    return q

def sorted_unique(items):
    return sorted(set(items or []), key=lambda n: n.lower())

# ----------------------------
# SIDEBAR 
# ----------------------------
with st.sidebar:
    st.markdown("### 🔐 Admin Login")
    if st.session_state.role != "admin":
        pw = st.text_input("Enter admin password", type="password")
        if st.button("Login"):
            if pw and pw == st.secrets.get("ADMIN_PASSWORD", ""):
                st.session_state.role = "admin"; st.success("Admin mode enabled"); st.rerun()
            else:
                st.error("Invalid password")
    else:
        st.success("Admin mode active")
        if st.button("Logout"):
            st.session_state.role = "guest"; st.rerun()

    st.markdown("---")
    # Quick Actions heading removed

    st.markdown("#### 🔎 Search by School")
    selected_school = st.selectbox(
        "Select a school:",
        [""] + list(schools.keys()),
        format_func=lambda x: f"{x} - {schools[x]}" if x else "-- Select School --"
    )
    if selected_school and st.button("🔍 Search School Publications"):
        st.session_state.current_query = f"faculty members of {selected_school}"
        st.rerun()

    st.markdown("---")
    st.markdown("#### 👥 Search by Faculty")
    school_filter = st.selectbox("Select a faculty…", ["All"] + list(schools.keys()), key="faculty_filter")

    def trigger_faculty_search(name: str):
        st.session_state.current_query = name
        st.session_state.faculty_clicked = name

    if school_filter == "All":
        all_fac = []
        for _, facs in st.session_state.chatbot.school_faculties.items():
            all_fac.extend(facs or [])
        for faculty in sorted_unique(all_fac):
            if st.button(faculty, key=f"fac_all_{faculty}", help="Click to view publications"):
                trigger_faculty_search(faculty); st.rerun()
    else:
        facs = st.session_state.chatbot.school_faculties.get(school_filter.upper(), [])
        for faculty in sorted_unique(facs):
            if st.button(faculty, key=f"fac_{school_filter}_{faculty}", help="Click to view publications"):
                trigger_faculty_search(faculty); st.rerun()

    st.markdown("---")
    st.markdown("### 📊 System Statistics")
    # Deterministic newsletters count: only unique PDF base names
    unique_pdfs = set()
    for src in st.session_state.chatbot.all_sources:
        s = (src or {}).get('source', '') or ''
        s = s.strip()
        if not s:
            continue
        if s.lower().endswith(".pdf") or ".pdf" in s.lower():
            part = s.split("/")[-1].split("\\")[-1]
            part = part.split("?")[0].split(",")[0].strip()
            if part.lower().endswith(".pdf"):
                unique_pdfs.add(part.lower())
    total_docs = len(unique_pdfs)
    total_schools = len(st.session_state.chatbot.school_faculties)
    total_faculty = sum(len(fac or []) for fac in st.session_state.chatbot.school_faculties.values())
    c1, c2 = st.columns(2)
    with c1:
        st.metric("Newsletters", total_docs)
        st.metric("Schools", total_schools)
    with c2:
        st.metric("Faculty", total_faculty)

# ----------------------------
# Tabs
# ----------------------------
if st.session_state.role == "admin":
    tab1, tab2, tab3 = st.tabs(["🔍 Search", "🗂️ Add Publications", "📋 Search History"])
else:
    tab1, tab3 = st.tabs(["🔍 Search", "📋 Search History"])
    tab2 = None

# ----------------------------
# Search tab
# ----------------------------
with tab1:
    st.markdown("### Search publications")
    col1, col2 = st.columns([3, 1])
    with col1:
        query = st.text_input(
            "Enter an author or a school",
            placeholder="e.g., K Satheesh Kumar OR faculty members of SoDS",
            key="search_input",
            value=st.session_state.get('current_query', '')
        )
    with col2:
        search_button = st.button("Search", use_container_width=True)

    # pick up triggered query from sidebar
    if st.session_state.get('current_query'):
        query = st.session_state.current_query
        st.session_state.current_query = ''

    if search_button or query:
        if (query or "").strip():
            with st.spinner("🔎 Searching publications..."):
                routed = route_query(query)
                answer = st.session_state.chatbot.answer_question(routed)
                # append to history
                st.session_state.chat_history.insert(0, {
                    'query': query,
                    'answer': answer,
                    'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
            st.markdown("### 📖 Results")
            st.markdown(answer)
        else:
            st.info("ℹ️ Please enter a search query")

# ----------------------------
# Add Publications (admin)
# ----------------------------
def append_publications_to_file(publications_text: str, source: str) -> int:
    path = Path(MAIN_PUBLICATIONS_FILE)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    pubs = [re.sub(r'^\s*[-•*\d\.\)\]]+\s*', '', p.strip()) for p in publications_text.splitlines() if p.strip()]
    block = "(Source: " + source.strip() + ")\n" + "\n".join(pubs) + "\n\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(block)
    return len(pubs)

def commit_to_github(commit_message: str) -> tuple[bool, str]:
    try:
        token = st.secrets.get("GITHUB_TOKEN", "")
        repo  = st.secrets.get("GITHUB_REPO", "")
        branch = st.secrets.get("GITHUB_BRANCH", "main")
        if not token or not repo:
            return False, "GitHub secrets not configured"
        subprocess.run(['git','config','user.email','duk-admin@example.com'], check=True)
        subprocess.run(['git','config','user.name','DUK ScholarSearch Admin'], check=True)
        subprocess.run(['git','add', MAIN_PUBLICATIONS_FILE], check=True)
        subprocess.run(['git','commit','-m', commit_message], check=True)
        remote_url = f"https://{token}@github.com/{repo}.git"
        subprocess.run(['git','push', remote_url, branch], check=True)
        return True, "Committed and pushed to GitHub."
    except subprocess.CalledProcessError as e:
        return False, f"Git error: {e}"
    except Exception as e:
        return False, f"Error: {e}"

if tab2 is not None:
    with tab2:
        st.markdown("### Add New Publications")
        if st.session_state.clear_inputs:
            st.session_state.publications_input = ""
            st.session_state.source_input = ""
            st.session_state.clear_inputs = False

        publications_input = st.text_area(
            "📰 Copy paste publication list from newsletters",
            placeholder="Author, A., & Author, B. (2025). Title... Journal ...\nAuthor, C. (2025). Title... Conference ...",
            height=220,
            key="publications_input",
            value=st.session_state.get('publications_input', '')
        )
        source_input = st.text_input("📰 Source (e.g., JAN 25 page 7):", key="source_input", value=st.session_state.get('source_input', ''))

        col_a, col_b = st.columns([1,1])
        with col_a:
            submit = st.button("➕ Add Publications", type="primary", use_container_width=True)
        with col_b:
            clear = st.button("🧹 Clear Inputs", use_container_width=True)

        if clear:
            st.session_state.publications_input = ""
            st.session_state.source_input = ""
            st.rerun()

        if submit:
            if not publications_input.strip():
                st.error("Please paste at least one publication"); st.stop()
            if not source_input.strip():
                st.error("Please provide source information"); st.stop()
            if len([l for l in publications_input.splitlines() if l.strip()]) > 200:
                st.error("Too many lines at once (limit 200). Please split into batches."); st.stop()

            with st.spinner("⏳ Adding and committing to GitHub..."):
                count = append_publications_to_file(publications_input, source_input)
                ok, msg = commit_to_github(f"Admin: add {count} publication(s) [{datetime.now().strftime('%Y-%m-%d %H:%M')}]")
                if ok:
                    st.success(f"✅ Added {count} publication(s). {msg}")
                    st.balloons()
                    st.session_state.clear_inputs = True
                    st.session_state.chatbot = PublicationChatbot(PUBLICATIONS_FOLDER, FACULTY_LISTS_FILE)
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(f"Failed to commit: {msg}")

# ----------------------------
# Search History tab 
# ----------------------------
with tab3:
    st.markdown("### 📋 Search History")
    if st.session_state.chat_history:
        if st.button("🗑️ Clear History"):
            st.session_state.chat_history = []
            st.rerun()
        st.markdown(f"**Total searches: {len(st.session_state.chat_history)}**")
        st.markdown("---")
        for entry in st.session_state.chat_history:
            st.markdown(f"#### 🔍 {entry['query']} — {entry['timestamp']}")
            st.markdown(entry["answer"])
            st.markdown("---")
    else:
        st.info("ℹ️ No search history yet. Start searching to see your history here!")

# ----------------------------
# Footer
# ----------------------------
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: #6B7280; padding: 1rem;'>
    <p>📚 Digital University Kerala - Publication Search System</p>
    <p>Powered by Sentence Transformers & FAISS</p>
</div>
""", unsafe_allow_html=True)
