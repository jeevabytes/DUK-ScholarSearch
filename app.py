import streamlit as st
import re
from pathlib import Path
import time
from datetime import datetime
from publications_search import PublicationChatbot
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
st.markdown("""
<style>
.main-header{
  font-size:2.6rem; font-weight:800; color:#1E3A8A; text-align:center;
  padding:1rem; background:linear-gradient(90deg,#EFF6FF 0%,#DBEAFE 100%);
  border-radius:10px; margin-bottom:1rem;
}
.sub-header{
  font-size:1.3rem; font-weight:600; color:#1F2937; text-align:center;
  margin-bottom:1.2rem;
}
.stButton>button{
  width:100%; background-color:#1E3A8A; color:white; font-weight:700;
  border-radius:8px; padding:0.55rem 1rem; border:none;
}
.stButton>button:hover{ background-color:#1E40AF; }
.publication-card{ background-color:#F9FAFB; padding:1rem; border-radius:8px;
  border-left:4px solid #1E3A8A; margin-bottom:1rem;}
.stats-box{ background-color:#EFF6FF; padding:1rem; border-radius:8px;
  text-align:center; border:2px solid #DBEAFE; }
</style>
""", unsafe_allow_html=True)

# ----------------------------
# Files
# ----------------------------
PUBLICATIONS_FILE = "publications.md"
FACULTY_LISTS_FILE = "faculty_list.md"

# ----------------------------
# Session init
# ----------------------------
if "chatbot" not in st.session_state:
    with st.spinner("🔄 Initializing system..."):
        st.session_state.chatbot = PublicationChatbot(PUBLICATIONS_FILE, FACULTY_LISTS_FILE)

    st.session_state.chat_history = []
    st.session_state.role = "guest"
    st.session_state.current_query = ""
    st.session_state.publications_input = ""
    st.session_state.source_input = ""


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


def route_query(q: str) -> str:
    if not q.strip():
        return ""
    t = q.lower().strip()

    # Detect school queries
    for code, full in schools.items():
        if full.lower() in t or code.lower() in t:
            return f"Publications of faculty members of {code}"

    # Else treat as name
    return f"Publications of {q.strip()}"


def sorted_unique(items):
    return sorted(set(items), key=lambda x: x.lower())


# ----------------------------
# Sidebar
# ----------------------------
with st.sidebar:
    st.markdown("### 🔐 Admin Login")
    if st.session_state.role != "admin":
        pw = st.text_input("Enter admin password", type="password")
        if st.button("Login"):
            if pw == st.secrets.get("ADMIN_PASSWORD", ""):
                st.session_state.role = "admin"
                st.rerun()
            else:
                st.error("Invalid password")
    else:
        st.success("Admin mode active")
        if st.button("Logout"):
            st.session_state.role = "guest"
            st.rerun()

    st.markdown("---")
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

    filter_choice = st.selectbox("Select school:", ["All"] + list(schools.keys()))

    if filter_choice == "All":
        all_fac = []
        for _, facs in st.session_state.chatbot.school_faculties.items():
            all_fac.extend(facs)
        show_list = sorted_unique(all_fac)
    else:
        show_list = sorted_unique(st.session_state.chatbot.get_school_faculties(filter_choice))

    for name in show_list:
        if st.button(name, key=f"facbtn_{name}"):
            st.session_state.current_query = name
            st.rerun()

    st.markdown("---")
    st.markdown("### 📊 System Statistics")
    st.metric("Schools", len(st.session_state.chatbot.school_faculties))
    st.metric("Faculty", sum(len(v) for v in st.session_state.chatbot.school_faculties.values()))

# ----------------------------
# Tabs
# ----------------------------
if st.session_state.role == "admin":
    tab_search, tab_pubs, tab_faculty, tab_history = st.tabs([
        "🔍 Search", "🗂️ Add Publications", "👥 Add Faculty Member", "📋 Search History"
    ])
else:
    tab_search, tab_history = st.tabs(["🔍 Search", "📋 Search History"])
    tab_pubs = None
    tab_faculty = None

# ----------------------------
# SEARCH TAB
# ----------------------------
with tab_search:
    st.markdown("### Search publications")

    query = st.text_input(
        "Enter author or school",
        value=st.session_state.get("current_query", ""),
        placeholder="Example: K Satheesh Kumar OR faculty members of SoDS"
    )

    search_btn = st.button("Search")

    if st.session_state.get("current_query"):
        query = st.session_state.current_query
        st.session_state.current_query = ""

    if search_btn or query:
        if query.strip():
            with st.spinner("🔎 Searching..."):
                routed = route_query(query)
                answer = st.session_state.chatbot.answer_question(routed)

                st.session_state.chat_history.insert(0, {
                    "query": query,
                    "answer": answer,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })

            st.markdown("### 📖 Results")
            st.markdown(answer)
        else:
            st.info("Please enter a query.")

# ----------------------------
# ADD PUBLICATIONS (ADMIN)
# ----------------------------
def append_publications(publications_text, source):
    path = Path(PUBLICATIONS_FILE)
    pubs = [re.sub(r'^\s*[-•*\d\.\)\]]+\s*', '', p.strip())
            for p in publications_text.splitlines() if p.strip()]

    block = f"(Source: {source.strip()})\n" + "\n".join(pubs) + "\n\n"
    path.write_text(path.read_text() + block, encoding="utf-8")
    return len(pubs)


def commit_to_github(msg):
    try:
        token = st.secrets.get("GITHUB_TOKEN", "")
        repo  = st.secrets.get("GITHUB_REPO", "")
        branch = st.secrets.get("GITHUB_BRANCH", "main")
        if not token or not repo:
            return False, "GitHub secrets missing"

        subprocess.run(['git','config','user.email','duk-admin@example.com'], check=True)
        subprocess.run(['git','config','user.name','DUK ScholarSearch Admin'], check=True)
        subprocess.run(['git','add', PUBLICATIONS_FILE], check=True)
        subprocess.run(['git','commit','-m', msg], check=True)

        remote = f"https://{token}@github.com/{repo}.git"
        subprocess.run(['git','push', remote, branch], check=True)

        return True, "Success"

    except Exception as e:
        return False, str(e)


if tab_pubs is not None:
    with tab_pubs:
        st.markdown("### 🗂️ Add New Publications")

        pub_text = st.text_area("Paste publications:", height=200)
        src = st.text_input("Source (e.g., JAN 25 page 7):")

        if st.button("➕ Add Publications"):
            if not pub_text.strip():
                st.error("Please paste at least one publication.")
                st.stop()
            if not src.strip():
                st.error("Please enter source information.")
                st.stop()

            count = append_publications(pub_text, src)
            ok, msg = commit_to_github(f"Add {count} publication(s)")
            if ok:
                st.success(f"Added {count} publications.")
                st.session_state.chatbot = PublicationChatbot(PUBLICATIONS_FILE, FACULTY_LISTS_FILE)
                st.rerun()
            else:
                st.error(msg)

# ----------------------------
# ADD FACULTY (ADMIN)
# ----------------------------
def append_faculty_to_file(school_code, faculty_names):
    path = Path(FACULTY_LISTS_FILE)
    content = path.read_text()

    header = f"# {schools[school_code]} ({school_code})"
    pos = content.find(header)
    if pos == -1:
        return -3

    end = content.find("\n", pos)
    if end == -1:
        end = len(content)

    section_end = content.find("\n# ", end)
    if section_end == -1:
        section_end = len(content)

    section_text = content[end:section_end]

    existing = set(
        line.replace("-", "").strip().lower()
        for line in section_text.splitlines() if line.strip().startswith("-")
    )

    new_list = [f for f in faculty_names if f.strip().lower() not in existing]

    if not new_list:
        return 0

    insertion = "".join(f"- {n}\n" for n in new_list)

    updated = content[:end+1] + insertion + content[end+1:]
    path.write_text(updated)

    return len(new_list)


if tab_faculty is not None:
    with tab_faculty:
        st.markdown("### 👥 Add Faculty Member")

        school_choice = st.selectbox(
            "Select school:",
            [""] + list(schools.keys()),
            format_func=lambda x: f"{x} - {schools[x]}" if x else "-- choose --"
        )

        faculty_input = st.text_area("Enter names (one per line):", height=150)

        if st.button("➕ Add Faculty"):
            if not school_choice:
                st.error("Select a school.")
                st.stop()

            names = [x.strip() for x in faculty_input.split("\n") if x.strip()]
            if not names:
                st.error("Enter at least one name.")
                st.stop()

            count = append_faculty_to_file(school_choice, names)

            if count == 0:
                st.warning("All names already exist.")
            elif count == -3:
                st.error("School section not found in faculty_list.md")
            else:
                st.success(f"Added {count} faculty member(s).")
                st.session_state.chatbot = PublicationChatbot(PUBLICATIONS_FILE, FACULTY_LISTS_FILE)
                st.rerun()

# ----------------------------
# SEARCH HISTORY
# ----------------------------
with tab_history:
    st.markdown("### 📋 Search History")

    if st.session_state.chat_history:
        if st.button("🗑️ Clear History"):
            st.session_state.chat_history = []
            st.rerun()

        for entry in st.session_state.chat_history:
            with st.expander(f"🔎 {entry['query']} — {entry['timestamp']}"):
                st.markdown(entry["answer"])
    else:
        st.info("No searches yet.")

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
