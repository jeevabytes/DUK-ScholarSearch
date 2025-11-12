import streamlit as st
import re
from pathlib import Path
import time
from datetime import datetime
from publications_search import PublicationChatbot
import os
import subprocess

st.set_page_config(page_title="DUK ScholarSearch", page_icon="📚", layout="wide", initial_sidebar_state="expanded")

PUBLICATIONS_FOLDER = "publications"
FACULTY_LISTS_FILE = "faculty_list.md"
MAIN_PUBLICATIONS_FILE = "publications/2025.md"

os.makedirs(PUBLICATIONS_FOLDER, exist_ok=True)

if 'chatbot' not in st.session_state:
    with st.spinner("Initializing publication search system..."):
        st.session_state.chatbot = PublicationChatbot(PUBLICATIONS_FOLDER, FACULTY_LISTS_FILE)
    st.session_state.chat_history = []
    st.session_state.current_query = ""
    st.session_state.role = "guest"
    st.session_state.publications_input = ""
    st.session_state.source_input = ""
    st.session_state.clear_inputs = False

schools = {
    "SoDS": "School of Digital Sciences",
    "SoCSE": "School of Computer Science and Engineering",
    "SoESA": "School of Electronic Systems and Automation",
    "SoI": "School of Informatics",
    "SoDiHLA": "School of Digital Humanities and Liberal Arts",
}
school_aliases = {k.lower(): k for k in schools}
school_aliases.update({v.lower(): k for k, v in schools.items()})

def is_school_query(text: str) -> str | None:
    t = (text or "").strip().lower()
    if not t:
        return None
    m = re.search(r"(faculty)?\s*members?\s*of\s*(.+)", t) or re.search(r"members\s*of\s*(.+)", t)
    if m:
        tail = re.sub(r"[^a-z ]", "", (m.group(2) if m.lastindex and m.lastindex >= 2 else m.group(1)) or "").strip()
        tail = re.sub(r"\s+", " ", tail).strip()
        if tail in school_aliases:
            return school_aliases[tail]
        for code, fullname in schools.items():
            if tail == code.lower() or code.lower() in tail or fullname.lower() in tail:
                return code
    return None

def is_plain_name_query(text: str) -> str | None:
    t = (text or "").strip()
    if not t or re.search(r"\bof\b", t, flags=re.IGNORECASE) or len(t) > 80:
        return None
    tokens = re.split(r"\s+", t)
    if len(tokens) == 0 or len(tokens) > 6:
        return None
    if not any(re.search(r"[A-Za-z]", tok) for tok in tokens):
        return None
    return t

st.title("DUK ScholarSearch")
st.caption("Search publications")

# MAIN TOP SEARCH
with st.container():
    col1, col2 = st.columns([3,1])
    with col1:
        query = st.text_input(
            "Enter an author or a school",
            placeholder="e.g., K Satheesh Kumar OR faculty members of SoDS",
            key="search_input",
            value=st.session_state.get("current_query", "")
        )
    with col2:
        go = st.button("Search", use_container_width=True)

def route_query(q: str) -> str:
    q = (q or "").strip()
    if not q:
        return ""
    school_code = is_school_query(q)
    if school_code:
        return f"Publications of faculty members of {school_code}"
    person = is_plain_name_query(q)
    if person:
        return f"Publications of {person}"
    return q

# SIDEBAR — layout preserved
with st.sidebar:
    st.markdown("### Admin Login")
    if st.session_state.role != "admin":
        pw = st.text_input("Enter admin password", type="password")
        if st.button("Login", key="admin_login_btn"):
            if pw and pw == st.secrets.get("ADMIN_PASSWORD"):
                st.session_state.role = "admin"
                st.success("Admin mode enabled")
                st.rerun()
            else:
                st.error("Invalid password")
    else:
        st.success("Admin mode active")
        if st.button("Logout", key="admin_logout_btn"):
            st.session_state.role = "guest"
            st.rerun()

    st.markdown("---")
    # Quick Actions heading removed intentionally

    # School section (unchanged placement)
    st.markdown("#### Search by School")
    selected_school = st.selectbox(
        "Select a school",
        [""] + list(schools.keys()),
        format_func=lambda x: f"{x} - {schools[x]}" if x in schools else ("-- Select School --" if x == "" else x),
        key="sb_school"
    )
    if selected_school and st.button("Search", key="sb_school_btn"):
        st.session_state.current_query = f"faculty members of {selected_school}"
        st.rerun()

    # Faculty section (unchanged placement, wording updated)
    st.markdown("#### Search by Faculty")
    school_filter = st.selectbox("Select a faculty…", ["All"] + list(schools.keys()), key="sb_faculty_filter")

    def sorted_unique(items):
        return sorted(set(items or []), key=lambda x: x.lower())

    if school_filter == "All":
        all_fac = []
        for fac_list in st.session_state.chatbot.school_faculties.values():
            all_fac.extend(fac_list or [])
        for name in sorted_unique(all_fac):
            if st.button(name, key=f"fac_all_{name}"):
                st.session_state.current_query = name
                st.rerun()
    else:
        fac_list = st.session_state.chatbot.school_faculties.get(school_filter.upper(), [])
        for name in sorted_unique(fac_list):
            if st.button(name, key=f"fac_{school_filter}_{name}"):
                st.session_state.current_query = name
                st.rerun()

# Run top search or sidebar triggers
if go or st.session_state.get("current_query"):
    effective = st.session_state.get("current_query") or query
    if (effective or "").strip():
        with st.spinner("Searching publications..."):
            routed = route_query(effective)
            answer = st.session_state.chatbot.answer_question(routed)
        st.session_state.chat_history.insert(0, {"query": effective, "answer": answer, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        st.markdown("#### Results")
        st.markdown(answer)
    else:
        st.info("Please enter a search query")

# Admin tab for adding publications
if st.session_state.role == "admin":
    with st.expander("Add New Publications", expanded=False):
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
        source_input = st.text_input("Source (e.g., JAN 25 page 7)", key="source_input", value=st.session_state.get("source_input", ""))

        colA, colB = st.columns(2)
        with colA:
            submit = st.button("Add Publications", type="primary", use_container_width=True)
        with colB:
            clear = st.button("Clear Inputs", use_container_width=True)

        def append_publications_to_file(publications_text: str, source: str) -> int:
            path = Path(MAIN_PUBLICATIONS_FILE)
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("start: empty (sectioning is based on 'Source' lines)\n", encoding="utf-8")
            pubs = [re.sub(r"^\\s*[-•\\d\\.\\)\\]]+\\s*", "", p.strip()) for p in publications_text.splitlines() if p.strip()]
            block = "\n" + "Source: " + source.strip() + "\n" + "\n".join(pubs) + "\n\n"
            with open(path, "a", encoding="utf-8") as f:
                f.write(block)
            return len(pubs)

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

        if clear:
            st.session_state.publications_input = ""
            st.session_state.source_input = ""
            st.rerun()

        if submit:
            if not publications_input.strip():
                st.error("Please paste at least one publication")
                st.stop()
            if not source_input.strip():
                st.error("Please provide source information")
                st.stop()
            if len([l for l in publications_input.splitlines() if l.strip()]) > 200:
                st.error("Too many lines at once (limit 200). Please split into batches.")
                st.stop()
            with st.spinner("Adding and committing to GitHub..."):
                count = append_publications_to_file(publications_input, source_input)
                ok, msg = commit_to_github(f"Admin add {count} publications {datetime.now().strftime('%Y-%m-%d %H:%M')}")
            if ok:
                st.success(f"Added {count} publications. {msg}")
                st.balloons()
                st.session_state.clear_inputs = True
                st.session_state.chatbot = PublicationChatbot(PUBLICATIONS_FOLDER, FACULTY_LISTS_FILE)
                time.sleep(1)
                st.rerun()
            else:
                st.error(f"Failed to commit: {msg}")

# Search history
with st.expander("Search History", expanded=False):
    if st.session_state.chat_history:
        if st.button("Clear History"):
            st.session_state.chat_history = []
            st.rerun()
        st.markdown(f"Total searches: {len(st.session_state.chat_history)}")
        st.markdown("---")
        for entry in st.session_state.chat_history:
            with st.expander(f"{entry['query']} - {entry['timestamp']}"):
                st.markdown(entry["answer"])
    else:
        st.info("No search history yet. Start searching to see your history here!")

# System Statistics at bottom
st.markdown("---")
st.markdown("### System Statistics")

unique_sources = set()
for src in st.session_state.chatbot.all_sources:
    source_text = src.get("source", "")
    if source_text and ".pdf" in source_text:
        unique_sources.add(source_text.split("/")[-1].strip())
    elif source_text and not source_text.endswith(".md"):
        unique_sources.add(source_text)

total_docs = len(unique_sources)
total_schools = len(st.session_state.chatbot.school_faculties)
total_faculty = sum(len(fac or []) for fac in st.session_state.chatbot.school_faculties.values())

c1, c2 = st.columns(2)
with c1:
    st.metric("Newsletters", total_docs)
    st.metric("Schools", total_schools)
with c2:
    st.metric("Faculty", total_faculty)
