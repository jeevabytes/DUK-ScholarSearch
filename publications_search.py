import re
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
from pathlib import Path

MONTHS = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC']
MONTH2NUM = {m:i+1 for i,m in enumerate(MONTHS)}

# Canonical school codes for display and storage
CANONICAL_CODES = {
    'SODS': 'SoDS',
    'SOCSE': 'SoCSE',
    'SOESA': 'SoESA',
    'SOI': 'SoI',
    'SODIHLA': 'SoDiHLA'
}

class PublicationChatbot:
    def __init__(self, publications_file, faculty_lists_file):
        self.all_documents = []
        self.all_sources = []
        self.faculty_lists_file = faculty_lists_file
        self.school_faculties = {}

        self.load_faculty_lists(faculty_lists_file)
        self.load_publication_files(publications_file)

        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        self.embeddings = self.model.encode(self.all_documents, show_progress_bar=False)

        dimension = self.embeddings.shape[1]
        self.index = faiss.IndexFlatL2(dimension)
        self.index.add(self.embeddings.astype('float32'))

    def load_faculty_lists(self, faculty_file):
        """Load faculty lists for all schools"""
        if not Path(faculty_file).exists():
            return

        with open(faculty_file, 'r', encoding='utf-8') as f:
            content = f.read()

        school_configs = {
            'SoDS': 'School of Digital Sciences',
            'SoCSE': 'School of Computer Science and Engineering',
            'SoESA': 'School of Electronic Systems and Automation',
            'SoI': 'School of Informatics',
            'SoDiHLA': 'School of Digital Humanities and Liberal Arts'
        }

        for school_code, full_name in school_configs.items():
            pattern = rf'#\s*{re.escape(full_name)}(?:\s*\({re.escape(school_code)}\))?\s*\n(.*?)(?=\n#\s|$)'
            school_match = re.search(pattern, content, re.DOTALL)

            if school_match:
                names = []
                section_text = school_match.group(1)

                for line in section_text.split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith('-') or line.startswith('*'):
                        name = line[1:].strip()
                        if name and len(name) > 1 and name[0].isupper():
                            names.append(name)

                if names:
                    # Store under canonical mixed-case key (not uppercased)
                    self.school_faculties[school_code] = names

    def load_publication_files(self, file_path):
        """
        Load publications from a single markdown file (e.g., publication.md)
        with flexible sectioning:
        - Start a new section on 'Source:' / '(Source:' lines.
        - Extract Source from the first 20 lines of each section.
        """
        file = Path(file_path)
        if not file.exists():
            return

        source_boundary_re = re.compile(r'^\s*\(?\s*Source\s*:', re.IGNORECASE)
        header_re = re.compile(r'^\s*#\s+')

        with open(file, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()

        sections = []
        current = []

        def flush_current():
            text = "\n".join(current).strip()
            if len(text) >= 50:  # noise guard
                sections.append(text)

        # Build sections using headers or Source lines as boundaries
        for line in lines:
            if header_re.match(line) or source_boundary_re.match(line):
                if current:
                    flush_current()
                    current = []
            current.append(line)

        if current:
            flush_current()

        # Extract heading + source from each section
        for section in sections:
            sec_lines = section.split("\n")

            # Heading: use '# ...' or first non-empty line
            heading = None
            for ln in sec_lines:
                if header_re.match(ln):
                    heading = ln.lstrip('#').strip()
                    break

            if not heading:
                for ln in sec_lines:
                    if ln.strip():
                        heading = ln.strip()
                        break
            if not heading:
                heading = file.name  # fallback

            # Source extraction
            first_lines = "\n".join(sec_lines[:20])
            m = re.search(r'\(\s*Source\s*:\s*([^)]+)\)', first_lines, re.IGNORECASE)
            if not m:
                m2 = re.search(r'^\s*Source\s*:\s*(.+)$', first_lines, re.IGNORECASE | re.MULTILINE)

            source = m.group(1).strip() if m else (m2.group(1).strip() if m2 else file.name)

            # Save section
            self.all_documents.append(section.strip())
            self.all_sources.append({
                'heading': heading,
                'source': source,
                'filename': file.name
            })

    # ---- Ordering helpers for Sources block ----
    def _parse_year_from(self, source_text, filename):
        s = (source_text or '').upper()
        m = re.search(r'(20\d{2})', s)
        if m:
            return int(m.group(1))
        mf = re.search(r'(20\d{2})', filename)
        return int(mf.group(1)) if mf else 9999

    def _parse_month_from(self, source_text):
        s = (source_text or '').upper()
        for m in MONTHS:
            if s.startswith(m) or f'{m} ' in s or f'{m}-' in s or f'{m}_' in s:
                return MONTH2NUM[m]
        return 99

    def _sort_sources(self, unique_sources, descending=True):
        keyed = []
        for i, d in enumerate(unique_sources):
            yr = self._parse_year_from(d.get('source',''), d.get('filename',''))
            mo = self._parse_month_from(d.get('source',''))
            keyed.append(((yr, mo, i), d))
        keyed.sort(key=lambda x: x[0], reverse=descending)
        return [d for _, d in keyed]

    # ---- Name handling and search ----
    def generate_name_variants(self, name):
        """Generate name variants - ALL CASES"""
        name = name.strip()
        parts = [p.rstrip('.') for p in name.split() if p]
        variants = set()

        if len(parts) == 1:
            variants.add(parts[0].lower())

        elif len(parts) == 2:
            f, l = parts
            f_lower, l_lower = f.lower(), l.lower()
            f_initial, l_initial = f[0].lower(), l[0].lower()

            if len(l) <= 2 and len(f) > 2:
                variants.update([
                    f"{f_lower} {l_lower}",
                    f"{l_lower} {f_lower}"
                ])
            elif len(f) <= 2 and len(l) > 2:
                variants.update([
                    f"{f_lower} {l_lower}",
                    f"{l_lower} {f_lower}"
                ])
            elif len(f) > 2 and len(l) > 2:
                variants.update([
                    f"{f_lower} {l_lower}",
                    f"{l_lower} {f_lower}",
                    f"{l_lower} {f_initial}",
                    f"{f_initial} {l_lower}",
                    f"{f_lower}{l_lower}",
                ])

        elif len(parts) == 3:
            f, m, l = parts
            f_lower, m_lower, l_lower = f.lower(), m.lower(), l.lower()
            f_initial, m_initial, l_initial = f[0].lower(), m[0].lower(), l[0].lower()

            is_f_initial = len(f) <= 2
            is_m_initial = len(m) <= 2
            is_l_initial = len(l) <= 2

            if not is_f_initial and is_m_initial and is_l_initial:
                variants.update([
                    f"{f_lower} {m_lower} {l_lower}",
                    f"{m_lower} {l_lower} {f_lower}",
                    f"{m_lower}{l_lower} {f_lower}",
                    f"{f_lower} {m_lower}{l_lower}",
                ])
            elif not is_f_initial and is_m_initial and not is_l_initial:
                variants.update([
                    f"{f_lower} {m_lower} {l_lower}",
                    f"{l_lower} {f_lower} {m_lower}",
                    f"{l_lower} {f_lower}{m_lower}",
                    f"{m_lower} {l_lower} {f_lower}",
                    f"{m_lower}{l_lower} {f_lower}",
                    f"{f_initial}{m_initial} {l_lower}",
                    f"{f_initial} {m_lower} {l_lower}",
                ])
            elif is_f_initial and not is_m_initial and not is_l_initial:
                variants.update([
                    f"{f_lower} {m_lower} {l_lower}",
                    f"{m_lower} {l_lower} {f_lower}",
                    f"{m_lower}{l_lower} {f_lower}",
                    f"{f_lower} {m_lower}{l_lower}",
                    f"{l_lower} {f_lower} {m_lower}",
                    f"{l_lower} {f_initial} {m_initial}",
                    f"{f_initial} {m_initial} {l_lower}",
                    f"{f_lower} {m_initial} {l_lower}",
                    f"{f_initial} {f_initial} {m_lower}",
                    f"{f_lower} {m_lower} {l_initial}",
                ])
            elif not is_f_initial and not is_m_initial and is_l_initial:
                variants.update([
                    f"{f_lower} {m_lower} {l_lower}",
                    f"{f_lower}{m_lower} {l_lower}",
                    f"{l_lower} {f_lower} {m_lower}",
                    f"{l_lower} {f_lower}{m_lower}",
                    f"{l_lower} {m_lower} {f_lower}",
                    f"{m_lower} {l_lower} {f_lower}",
                    f"{l_lower} {f_lower} {m_initial}",
                    f"{f_lower} {m_initial} {l_lower}",
                    f"{l_lower} {m_lower} {f_initial}",
                    f"{m_lower} {l_lower} {f_initial}",
                ])
            elif is_f_initial and is_m_initial and not is_l_initial:
                variants.update([
                    f"{f_lower} {m_lower} {l_lower}",
                    f"{m_lower} {l_lower} {f_lower}",
                    f"{l_lower} {f_lower} {m_lower}",
                    f"{f_lower}{m_lower} {l_lower}",
                    f"{l_lower} {f_lower}{m_lower}",
                ])
            elif is_f_initial and not is_m_initial and is_l_initial:
                variants.update([
                    f"{f_lower} {m_lower} {l_lower}",
                    f"{m_lower} {f_lower} {l_lower}",
                    f"{f_lower}{l_lower} {m_lower}",
                    f"{f_lower} {l_lower} {m_lower}",
                ])
            else:
                variants.update([
                    f"{f_lower} {m_lower} {l_lower}",
                    f"{f_lower} {m_lower} {l_initial}",
                    f"{f_lower} {m_lower}",
                    f"{m_lower} {f_lower} {l_initial}",
                    f"{m_lower} {f_lower} {l_lower}",
                    f"{m_lower} {f_lower}",
                    f"{l_lower} {f_lower} {m_lower}",
                    f"{l_lower} {f_initial} {m_initial}",
                    f"{l_lower} {f_lower} {m_initial}",
                    f"{f_initial} {m_initial} {l_lower}",
                    f"{f_lower} {m_initial} {l_lower}",
                    f"{m_lower} {f_initial} {l_lower}",
                ])

        elif len(parts) == 4:
            f, m1, m2, l = parts
            f_lower, m1_lower, m2_lower, l_lower = f.lower(), m1.lower(), m2.lower(), l.lower()
            f_initial, m1_initial, m2_initial, l_initial = f[0].lower(), m1[0].lower(), m2[0].lower(), l[0].lower()

            is_f_initial = len(f) <= 2
            is_m1_initial = len(m1) <= 2
            is_m2_initial = len(m2) <= 2
            is_l_initial = len(l) <= 2

            if is_f_initial and is_m1_initial and not is_m2_initial and not is_l_initial:
                variants.update([
                    f"{f_lower} {m1_lower} {m2_lower} {l_lower}",
                    f"{l_lower} {f_lower} {m1_lower} {m2_lower}",
                    f"{f_lower}{m1_lower} {m2_lower} {l_lower}",
                    f"{f_lower} {m1_lower} {m2_initial} {l_lower}",
                    f"{f_lower}{m1_lower} {m2_lower}{l_lower}",
                    f"{l_lower} {f_lower} {m1_lower} {m2_initial}",
                    f"{m2_lower} {l_lower} {f_lower} {m1_lower}",
                ])
            elif not is_f_initial and not is_m1_initial and is_m2_initial and is_l_initial:
                variants.update([
                    f"{f_lower} {m1_lower} {m2_lower} {l_lower}",
                    f"{l_lower} {f_lower} {m1_lower} {m2_lower}",
                    f"{m2_lower}{l_lower} {f_lower} {m1_lower}",
                    f"{m2_lower} {l_lower} {f_lower} {m1_lower}",
                    f"{f_lower}{m1_lower} {m2_lower} {l_lower}",
                    f"{m1_lower} {m2_lower} {l_lower} {f_lower}",
                    f"{m1_lower} {m2_lower} {l_lower} {f_initial}",
                ])
            else:
                variants.update([
                    f"{f_lower} {m1_lower} {m2_lower} {l_lower}",
                    f"{l_lower} {f_lower} {m1_lower} {m2_lower}",
                ])

        elif len(parts) > 4:
            f, *middle_parts, l = parts
            f_lower, l_lower = f.lower(), l.lower()
            middle_lower = [p.lower() for p in middle_parts]
            full_name = ' '.join([f_lower] + middle_lower + [l_lower])
            variants.update([
                full_name,
                f"{l_lower} {f_lower} {' '.join(middle_lower)}",
            ])

        return list(variants)

    def normalize_for_matching(self, text):
        """Normalize text by removing punctuation but keeping word boundaries"""
        normalized = re.sub(r'[.,;:()\[\]{}"\'-]+', ' ', text.lower())
        normalized = re.sub(r'\s+', ' ', normalized)
        return normalized

    def search_publications(self, name):
        """Search publications for a given name - PUNCTUATION AGNOSTIC"""
        variants = self.generate_name_variants(name)
        pubs = []
        pub_sources = []

        for doc, src in zip(self.all_documents, self.all_sources):
            for line in doc.split('\n'):
                if len(line) < 40:
                    continue

                normalized_line = self.normalize_for_matching(line)

                matched = False
                for variant in variants:
                    tokens = variant.split()
                    if len(tokens) == 0:
                        continue
                    pattern_parts = [re.escape(token) for token in tokens]
                    pattern = r'\b' + r'[\s.,;:()\[\]{}\"\'-]{0,3}'.join(pattern_parts) + r'\b'
                    if re.search(pattern, normalized_line):
                        matched = True
                        break

                if matched:
                    clean = re.sub(r'^[-•*►#\d\.\s]+', '', line.strip())
                    if len(clean) > 30 and clean not in pubs:
                        pubs.append(clean)
                        pub_sources.append(src)

        return pubs, pub_sources

    def get_school_faculties(self, school_code):
        """Get faculty list for a specific school (accepts upper or canonical)"""
        key = CANONICAL_CODES.get(school_code.upper(), school_code)
        return self.school_faculties.get(key, [])

    def _unique_sources(self, sources):
        """Return list of unique source dicts (dedup by source string)"""
        seen = set()
        unique = []
        for src in sources:
            key = src['source']
            if key not in seen:
                seen.add(key)
                unique.append(src)
        return unique

    def format_sources(self, sources, descending=True):
        """Format sources for display with yearwise + monthwise ordering"""
        unique = self._unique_sources(sources)
        if not unique:
            return "\n\n**Sources:**\n- Unknown"
        ordered = self._sort_sources(unique, descending=descending)
        return "\n\n**Sources:**\n" + "\n".join(f"- {d['source']}" for d in ordered)

    def answer_question(self, question):
        """Main function to answer publication queries"""
        if not question.strip():
            return "Please ask something like:\n  - [Person Name]\n  - Faculty members of [School Name]"

        q_lower = question.lower()

        # School-specific faculty queries
        school_patterns = {
            'SODS': ['sods', 'school of digital sciences'],
            'SOCSE': ['socse', 'school of computer science and engineering'],
            'SOESA': ['soesa', 'school of electronic systems and automation'],
            'SOI': ['soi', 'school of informatics'],
            'SODIHLA': ['sodihla', 'school of digital humanities and liberal arts']
        }

        for school, keywords in school_patterns.items():
            if any(kw in q_lower for kw in keywords) and any(term in q_lower for term in ['faculty', 'all', 'members']):
                faculty_names = self.get_school_faculties(school)

                if not faculty_names:
                    # Keep message in uppercase code if data missing; optional to map back
                    return f"Could not find faculty list for {CANONICAL_CODES.get(school, school)}."

                faculty_pub_counts = {}
                all_pubs = []
                all_sources = []

                for name in faculty_names:
                    pubs, sources = self.search_publications(name)
                    faculty_pub_counts[name] = len(pubs)

                    for p, s in zip(pubs, sources):
                        if p not in all_pubs:
                            all_pubs.append(p)
                            all_sources.append(s)

                if all_pubs:
                    display_school = CANONICAL_CODES.get(school, school)
                    summary = f"Publications by {display_school} faculty members ({len(faculty_names)} faculty members):\n\n"
                    summary += "**Faculty Publication Count:**\n"
                    for name in faculty_names:
                        count = faculty_pub_counts.get(name, 0)
                        summary += f"  • {name}: {count} publication{'s' if count != 1 else ''}\n"

                    summary += f"\n**Total: {len(all_pubs)} publication{'s' if len(all_pubs) != 1 else ''}**\n\n"
                    summary += "---\n\n"
                    summary += "\n".join(f"{i}. {p}" for i, p in enumerate(all_pubs, 1))
                    summary += self.format_sources(all_sources, descending=True)
                    return summary

                return f"No publications found for {CANONICAL_CODES.get(school, school)} faculties."

        # Extract faculty name from query
        name_patterns = [
            r'(?:publications?|papers?|research|articles?|journals?)\s+(?:of|by)\s+([\w\s.]+?)(?:\?|$)',
            r'([\w\s.]+?)\s+(?:publications?|papers?|research|articles?)(?:\?|$)',
        ]

        name = None
        for pattern in name_patterns:
            match = re.search(pattern, question, re.IGNORECASE)
            if match:
                name = match.group(1).strip().rstrip('?').strip()
                if name:
                    name = ' '.join(word.capitalize() for word in name.split())
                    break

        if name:
            pubs, sources = self.search_publications(name)
            if pubs:
                return (
                    f"Publications by {name}:\n\n"
                    + "\n".join(f"{i}. {p}" for i, p in enumerate(pubs, 1))
                    + self.format_sources(sources, descending=True)
                )
            return f"No publications found for {name}."

        return "Please ask something like:\n  - [Person Name]\n  - Faculty members of [School Name]"
