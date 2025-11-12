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
# Styles
# ----------------------------
st.markdown(
    """
    <style>
    .main-header { font-size: 2.5rem; font-weight: bold; color:#1E3A8A; text-align:center; padding:1rem;
                   background: linear-gradient(90deg,#EFF6FF 0%, #DBEAFE 100%); border-radius:10px; margin-bottom:2rem;}
    .sub-header { font-size:1.2rem; color:#374151; text-align:center; margin-bottom:2rem;}
    .stButton>button { width:100%; background-color:#1E3A8A; color:white; font-weight:bold; border-radius:8px;
                       padding:0.5rem 1rem; border:none;}
    .stButton>button:hover { background-color:#1E40AF; }
    .publication-card { background-color:#F9FAFB; padding:1rem; border-radius:8px; border-left:4px solid #1E3A8A; margin-bottom:1rem;}
    .stats-box { background-color:#EFF6FF; padding:1rem; border-radius:8px; text-align:center; border:2px solid #DBEAFE;}
    .faculty-btn button { width:100%; background-color:#FFFFFF; color:#111827; text-align:left; border:1px solid #E5E7EB;
                          border-radius:6px; padding:0.4rem 0.6rem; margin-bottom:0.25rem;}
    .faculty-btn button:hover { background-color:#F3F4F6; border-color:#D1D5DB;}
    .upload-section { background-color:#F0FDF4; padding:1.5rem; border-radius:10px; border:2px dashed #10B981; margin:1rem 0;}
    .example-box { background-color:#F3F4F6; padding:1rem; border-radius:8px; border-left:4px solid #10B981;
                   font-family:monospace; font-size:0.9rem; margin-top:1rem;}
    </style>
    """,
    unsafe_allow_html=True
)

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
    with st.spinner("Initializing publication search system..."):
        st.session_state.chatbot = PublicationChatbot(PUBLICATIONS_FOLDER, FACULTY_LISTS_FILE)
    st.session_state.chat_history = []
    st.session_state.current_query = ""
    st.session_state.role = "guest"   # guest | admin
    st.session_state.publications_input = ""
    st.session_state.source_input = ""
    st.session_state.clear_inputs = False

# ----------------------------
# Header
# ----------------------------
st.markdown('<div class="main-header">DUK ScholarSearch</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Search publications</div>', unsafe_allow_html=True)

# ----------------------------
# School dictionary and helpers
# ----------------------------
schools = {
    "SoDS": "School of Digital Sciences",
    "SoCSE": "School of Computer Science and Engineering",
    "SoESA": "School of Electronic Systems and Automation",
    "SoI": "School of Informatics",
    "SoDiHLA": "School of Digital Humanities and Liberal Arts",
}
school_aliases = {k.lower(): k for k in schools.keys()}
school_aliases.update({v.lower(): k for k, v in schools.items()})

def is_school_query(text: str) -> str | None:
    t = (text or "").strip().lower()
    if not t:
        return None
    m = re.search(r"(faculty)?\s*members?\s*of\s*(.+)", t)
    if not m:
        m = re.search(r"members\s*of\s*(.+)", t)
    if m:
        tail = re.sub(r"[^a-z ]", "", m.group(1 if m.lastindex == 1 else 2) or "").strip()
        tail = re.sub(r"\s+", " ", tail).strip()
        if tail in school_aliases:
            return school_aliases[tail]
        for code in schools.keys():
            if tail == code.lower() or code.lower() in tail:
                return code
        for code, fullname in schools.items():
            if fullname.lower() in tail:
                return code
    return None

def is_plain_name_query(text: str) -> str | None:
    t = (text or "").strip()
    if not t:
        return None
    if re.search(r"\bof\b", t, flags=re.IGNORECASE):
        return None
    if len(t) > 80:
        return None
    tokens = re.split(r"\s+", t)
    if len(tokens) == 0 or len(tokens) > 6:
        return None
    alpha_tokens = [tok for tok in tokens if re.search(r"[A-Za-z]", tok)]
    if not alpha_tokens:
        return None
    return t

# ----------------------------
# Admin sidebar
# ----------------------------
with st.sidebar:
    st.markdown("### Admin Login")
    if st.session_state.role != "admin":
        pw = st.text_input("Enter admin password", type="password")
        if st.button("Login"):
            if pw and pw == st.secrets.get("ADMIN_PASSWORD"):
                st.session_state.role = "admin"
                st.success("Admin mode enabled")
                st.rerun()
            else:
                st.error("Invalid password")
    else:
        st.success("Admin mode active")
        if st.button("Logout"):
            st.session_state.role = "guest"
            st.rerun()

# ----------------------------
# Schoolwise search + Faculty view (together)
# ----------------------------
st.markdown("---")
st.markdown("### Search by School")

selected_school = st.selectbox(
    "Select a school",
    [""] + list(schools.keys()),
    format_func=lambda x: f"{x} - {schools[x]}" if x in schools else ("-- Select School --" if x == "" else x)
)

col_school_btn, col_faculty_anchor = st.columns([1, 1])
with col_school_btn:
    if selected_school and st.button("Search", key="search_school_btn"):
        st.session_state.current_query = f"faculty members of {selected_school}"
        st.rerun()

# Faculty view section placed just below schoolwise selection
st.markdown("### Search by Faculty")

school_filter = st.selectbox("Select a faculty…", ["All"] + list(schools.keys()), key="faculty_filter")

def trigger_faculty_search(name: str):
    st.session_state.current_query = name
    st.session_state.faculty_clicked = name

def sorted_unique(iterable):
    return sorted(set(iterable), key=lambda x: (x.lower(), x))

if school_filter == "All":
    # Aggregate all faculty and sort alphabetically
    all_fac = []
    for fac_list in st.session_state.chatbot.school_faculties.values():
        all_fac.extend(fac_list or [])
    all_fac = sorted_unique(all_fac)
    if all_fac:
        st.markdown(f"Showing {len(all_fac)} faculty (All schools)")
        for faculty in all_fac:
            if st.button(faculty, key=f"fac_all_{faculty}", help="Click to view publications", type="secondary"):
                trigger_faculty_search(faculty)
                st.rerun()
    else:
        st.info("No faculty data available for All")
else:
    fac_list = st.session_state.chatbot.school_faculties.get(school_filter.upper(), [])
    fac_list = sorted_unique(fac_list or [])
    if fac_list:
        st.markdown(f"{school_filter} — {len(fac_list)} members")
        for faculty in fac_list:
            if st.button(faculty, key=f"fac_{school_filter}_{faculty}", help="Click to view publications", type="secondary"):
                trigger_faculty_search(faculty)
                st.rerun()
    else:
        st.info(f"No faculty data available for {school_filter}")

# ----------------------------
# Tabs
# ----------------------------
if st.session_state.role == "admin":
    tab1, tab2, tab3 = st.tabs(["Search", "Add Publications", "Search History"])
else:
    tab1, tab3 = st.tabs(["Search", "Search History"])
    tab2 = None

# ----------------------------
# Search tab
# ----------------------------
with tab1:
    st.markdown("### Search")

    col1, col2 = st.columns([3, 1])
    with col1:
        query = st.text_input(
            "Enter an author or a school",
            placeholder="e.g., K Satheesh Kumar OR faculty members of SoDS",
            key="search_input",
            value=st.session_state.get("current_query", "")
        )
    with col2:
        searchbutton = st.button("Search", use_container_width=True)

    # Route and execute query
    if "current_query" in st.session_state and st.session_state.current_query:
        query = st.session_state.current_query

    def route_query(q: str) -> str:
        q = (q or "").strip()
        if not q:
            return ""
        school_code = is_school_query(q)
        if school_code:
            return f"Publications of faculty members of {school_code}"
        plain_name = is_plain_name_query(q)
        if plain_name:
            return f"Publications of {plain_name}"
        return q

    if searchbutton or query:
        if (query or "").strip():
            with st.spinner("Searching publications..."):
                routed = route_query(query)
                answer = st.session_state.chatbot.answer_question(routed)
            st.session_state.chat_history.insert(0, {
                "query": query,
                "answer": answer,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            st.markdown("#### Results")
            st.markdown(answer)
        else:
            st.info("Please enter a search query")

# ----------------------------
# Add publications tab (admin)
# ----------------------------
def append_publications_to_file(publications_text: str, source: str) -> int:
    # Ensure file exists
    path = Path(MAIN_PUBLICATIONS_FILE)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("start: empty (sectioning is based on 'Source' lines)\n")
    # Build block
    block_lines = []
    block_lines.append(f"Source: {source.strip()}\n")
    publications = [p.strip() for p in publications_text.strip().split("\n") if p.strip()]
    for pub in publications:
        pub = re.sub(r"^\s*[-•\d\.\)\]]+\s*", "", pub)  # strip bullets, numbers
        block_lines.append(pub + "\n")
    block_text = "\n" + "".join(block_lines) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(block_text)
    return len(publications)

def commit_to_github(commit_message: str) -> tuple[bool, str]:
    try:
        token = st.secrets.get("GITHUB_TOKEN")
        repo = st.secrets.get("GITHUB_REPO")
        branch = st.secrets.get("GITHUB_BRANCH", "main")
        if not token or not repo:
            return False, "GitHub secrets not configured"
        subprocess.run(["git", "config", "user.email", "duk-admin@example.com"], check=True)
        subprocess.run(["git", "config", "user.name", "DUK ScholarSearch Admin"], check=True)
        subprocess.run(["git", "add", MAIN_PUBLICATIONS_FILE], check=True)
        subprocess.run(["git", "commit", "-m", commit_message], check=True)
        remote_url = f"https://{token}@github.com/{repo}.git"
        subprocess.run(["git", "push", remote_url, branch], check=True)
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

        publications_input = st.textarea(
            "Copy paste publication list from newsletters",
            placeholder="Author, A., Author, B. (2025). Title... Journal ...\nC., D. (2025). Title... Conference ...",
            height=220,
            key="publications_input",
            value=st.session_state.get("publications_input", "")
        )
        source_input = st.text_input(
            "Source (e.g., JAN 25 page 7)",
            key="source_input",
            value=st.session_state.get("source_input", "")
        )

        cola, colb = st.columns(2)
        with cola:
            submit = st.button("Add Publications", type="primary", use_container_width=True)
        with colb:
            clear = st.button("Clear Inputs", use_container_width=True)

        if clear:
            st.session_state.publications_input = ""
            st.session_state.source_input = ""
            st.experimental_rerun()

        if submit:
            if not publications_input.strip():
                st.error("Please paste at least one publication")
                st.stop()
            if not source_input.strip():
                st.error("Please provide source information")
                st.stop()
            lines = [l for l in publications_input.splitlines() if l.strip()]
            if len(lines) > 200:
                st.error("Too many lines at once (limit 200). Please split into batches.")
                st.stop()

            with st.spinner("Adding and committing to GitHub..."):
                count = append_publications_to_file(publications_input, source_input)
                ok, msg = commit_to_github(f"Admin add {count} publications {datetime.now().strftime('%Y-%m-%d %H:%M')}")
            if ok:
                st.success(f"Added {count} publications. {msg}")
                st.balloons()
                st.session_state.clear_inputs = True
                # Reinitialize chatbot so new data is searchable
                st.session_state.chatbot = PublicationChatbot(PUBLICATIONS_FOLDER, FACULTY_LISTS_FILE)
                time.sleep(1)
                st.rerun()
            else:
                st.error(f"Failed to commit: {msg}")

# ----------------------------
# Search history
# ----------------------------
with tab3:
    st.markdown("### Search History")
    if st.session_state.chat_history:
        if st.button("Clear History"):
            st.session_state.chat_history = []
            st.rerun()
        st.markdown(f"Total searches: {len(st.session_state.chat_history)}")
        st.markdown("---")
        for idx, entry in enumerate(st.session_state.chat_history):
            with st.expander(f"{entry['query']} - {entry['timestamp']}"):
                st.markdown(entry["answer"])
    else:
        st.info("No search history yet. Start searching to see your history here!")

# ----------------------------
# System statistics (moved to bottom)
# ----------------------------
st.markdown("---")
st.markdown("### System Statistics")

unique_sources = set()
for src in st.session_state.chatbot.all_sources:
    source_text = src.get("source", "")
    if source_text and ".pdf" in source_text:
        pdfname = source_text.split("/")[-1].strip()
        unique_sources.add(pdfname)
    elif source_text and not source_text.endswith(".md"):
        unique_sources.add(source_text)

total_docs = len(unique_sources)
total_schools = len(st.session_state.chatbot.school_faculties)
total_faculty = sum(len(fac or []) for fac in st.session_state.chatbot.school_faculties.values())

col1, col2 = st.columns(2)
with col1:
    st.metric("Newsletters", total_docs)
    st.metric("Schools", total_schools)
with col2:
    st.metric("Faculty", total_faculty)

st.markdown("---")
st.markdown(
    '<div style="text-align:center;color:#6B7280;padding:1rem;">'
    '<p>Digital University Kerala - Publication Search System</p>'
    '<p>Powered by Sentence Transformers & FAISS</p>'
    '</div>',
    unsafe_allow_html=True
)
