#!/usr/bin/env python3
"""
Discovery Objections GUI v3.1
=============================

Integrated GUI with:
- Flexible file selection (browse + multi-select)
- Dynamic column detection (works with any matrix column names)
- Multiple discovery/matrix pair processing
- Flexible discovery format parsing
- Explanation temperature control
- Includes case summary and preliminary objections in prompts
"""

import csv
import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
from pathlib import Path
from datetime import datetime

# =============================================================================
# CONFIGURATION
# =============================================================================

BASE_DIR = Path(__file__).parent.resolve()
CASE_SUMMARY_FILE = BASE_DIR / "case_summary.txt"
OBJECTION_LANG_FILE = BASE_DIR / "objection_language.txt"
PRELIMINARY_OBJ_FILE = BASE_DIR / "preliminary_objections.txt"
SMART_SYNC = BASE_DIR / "smart_sync.py"

# Known objection column aliases - maps various names to canonical form
COLUMN_ALIASES = {
    "Relevance": ["relevance", "relevant", "irrelevant"],
    "Compound": ["compound"],
    "Vague": ["vague", "vague & ambiguous", "vague and ambiguous", "vague/ambiguous", 
              "ambiguous", "vague, ambiguous", "vague ambiguous"],
    "Speculation": ["speculation", "speculative", "calls for speculation"],
    "Assumes Facts": ["assumes facts", "assumes", "assumption", "assumes facts not in evidence"],
    "Expert Opinion": ["expert opinion", "expert", "calls for expert"],
    "Legal Conclusion": ["legal conclusion", "legal", "conclusion", "seeks legal conclusion"],
    "Overbroad": ["overbroad", "overbroad and unduly burdensome", "overbroad-scope", 
                  "overbroad (scope)", "scope"],
    "Duplicative": ["duplicative", "duplicate", "duplicative and harassing"],
    "ESI-Burden": ["esi burden", "esi-burden", "esi", "undue burden (esi)"],
    "Oppressive": ["oppressive", "oppressive and harassing", "burdensome", "oppressive/burdensome"],
    "Not-Complete": ["not full/complete", "not full and complete", "not-complete", 
                     "not complete", "not full"],
    "Annoyance": ["annoyance", "unwarranted annoyance", "embarrassment"],
    "Equally-Avail": ["equally available", "equally avail", "equally-avail"],
    "Public-Domain": ["public domain", "public-domain", "public domain / access"],
    "Atty-Client": ["attorney-client", "atty-client", "attorney client", "ac privilege", "a-c"],
    "Work-Product": ["work product", "work-product", "attorney work product", "wp"],
    "Privacy-RP": ["privacy (rp)", "privacy-rp", "privacy rp", "privacy (responding party)", "privacy"],
    "Privacy-3rd": ["privacy (3rd)", "privacy-3rd", "privacy 3rd", "privacy (third parties)", 
                    "third party privacy"],
    "Joint-Defense": ["joint defense", "joint-defense", "joint defense privilege"],
    "Anticipation": ["anticipation", "anticipation of litigation"],
    "Premature": ["premature", "premature discovery", "premature expert"],
    "Settlement-Priv": ["settlement priv", "settlement", "settlement privilege"],
    "Def-Overbroad": ["def-overbroad", "definition overbroad"],
}

# Build reverse lookup
ALIAS_TO_CANONICAL = {}
for canonical, aliases in COLUMN_ALIASES.items():
    for alias in aliases:
        ALIAS_TO_CANONICAL[alias.lower().strip()] = canonical

# Template numbers matching objection_language.txt
CANONICAL_TO_TEMPLATE = {
    "Relevance": "1",
    "Compound": "2",
    "Vague": "3",
    "Speculation": "4",
    "Assumes Facts": "5",
    "Expert Opinion": "6",
    "Legal Conclusion": "7",
    "Overbroad": "8",
    "Duplicative": "9",
    "ESI-Burden": "10",
    "Oppressive": "11",
    "Not-Complete": "12",
    "Annoyance": "13",
    "Equally-Avail": "14",
    "Public-Domain": "15",
    "Atty-Client": "16",
    "Work-Product": "17",
    "Privacy-RP": "18",
    "Privacy-3rd": "19",
    "Joint-Defense": "20",
    "Anticipation": "21",
    "Premature": "22",
    "Settlement-Priv": "23",
    "Def-Overbroad": "24",
}

# Explanation temperature levels
TEMP_LEVELS = {
    0: ("Minimal", "Use approved templates only. No case-specific reasoning."),
    1: ("Low", "Add brief reasoning from cell notes only (1 sentence max)."),
    2: ("Medium", "Add reasoning from cell notes and Notes/comments column (1-2 sentences)."),
    3: ("High", "Full reasoning from case summary, notes, and comments (2-3 sentences)."),
}

# Skip these txt files
SKIP_TXT_FILES = {"case_summary.txt", "objection_language.txt", "preliminary_objections.txt"}


# =============================================================================
# FLEXIBLE PARSING
# =============================================================================

def normalize_column_name(col_name):
    """Convert a column name to its canonical form, or return original if unknown."""
    if not col_name:
        return None
    lower = col_name.strip().lower()
    return ALIAS_TO_CANONICAL.get(lower, col_name)


def is_notes_column(col_name):
    """Check if a column is likely the notes/comments column."""
    if not col_name:
        return False
    lower = col_name.strip().lower()
    return lower in ("notes", "comments", "note", "comment", "remarks")


def is_request_column(col_name):
    """Check if a column is the request number column."""
    if not col_name:
        return False
    lower = col_name.strip().lower()
    return lower in ("request", "req", "no", "no.", "number", "request no", "request no.", 
                     "interrogatory", "rog", "rfa", "rpd")


def parse_discovery_file_flexible(filepath):
    """
    Flexibly parse discovery requests from various formats.
    Returns {request_num: text}
    """
    content = filepath.read_text(encoding="utf-8")
    requests = {}
    
    # Pattern 1: "Form Interrogatory No. X.X" (with optional quotes around text)
    for match in re.finditer(
        r'Form\s+Interrogatory\s+No\.\s*(\d+\.?\d*)\s*[:\n]?\s*["\']?(.*?)["\']?\s*(?=Form\s+Interrogatory\s+No\.|$)',
        content, re.DOTALL | re.IGNORECASE
    ):
        num = match.group(1).strip()
        text = match.group(2).strip().strip('"\'')
        if text:
            requests[num] = text
    
    if requests:
        return requests
    
    # Pattern 2: "REQUEST FOR ADMISSION NO. X"
    for match in re.finditer(
        r'REQUEST\s+FOR\s+ADMISSION\s+NO\.\s*(\d+)[:\s]+(.*?)(?=REQUEST\s+FOR\s+ADMISSION\s+NO\.|$)',
        content, re.DOTALL | re.IGNORECASE
    ):
        requests[match.group(1)] = match.group(2).strip()
    
    if requests:
        return requests
    
    # Pattern 3: "REQUEST FOR PRODUCTION NO. X"
    for match in re.finditer(
        r'REQUEST\s+FOR\s+PRODUCTION\s+(?:OF\s+DOCUMENTS\s+)?NO\.\s*(\d+)[:\s]+(.*?)(?=REQUEST\s+FOR\s+PRODUCTION|$)',
        content, re.DOTALL | re.IGNORECASE
    ):
        requests[match.group(1)] = match.group(2).strip()
    
    if requests:
        return requests
    
    # Pattern 4: "INTERROGATORY NO. X" or "SPECIAL INTERROGATORY NO. X"
    for match in re.finditer(
        r'(?:SPECIAL\s+)?INTERROGATORY\s+NO\.\s*(\d+)[:\s]+(.*?)(?=(?:SPECIAL\s+)?INTERROGATORY\s+NO\.|$)',
        content, re.DOTALL | re.IGNORECASE
    ):
        requests[match.group(1)] = match.group(2).strip()
    
    if requests:
        return requests
    
    # Pattern 5: Bare "X.X" at start of line (FROG style)
    for match in re.finditer(
        r'^(\d+\.\d+)\s+(.*?)(?=^\d+\.\d+\s|\Z)',
        content, re.MULTILINE | re.DOTALL
    ):
        text = match.group(2).strip()
        if len(text) > 20:  # Filter out too-short matches
            requests[match.group(1)] = text
    
    return requests


def parse_matrix_cell(cell_value):
    """
    Parse a matrix cell value.
    Returns: (should_use: bool, notes: str or None)
    """
    if not cell_value:
        return (False, None)
    
    val = str(cell_value).strip()
    if not val:
        return (False, None)
    
    # Check for "x; notes" pattern
    if ";" in val:
        parts = val.split(";", 1)
        notes = parts[1].strip() if len(parts) > 1 else None
        return (True, notes if notes else None)
    
    # Check for bare X
    if val.upper() in ("X", "YES", "Y", "1", "TRUE"):
        return (True, None)
    
    # Any other content = use with content as notes
    return (True, val)


def parse_matrix_flexible(csv_path):
    """
    Flexibly parse CSV matrix, auto-detecting column purposes.
    """
    rows = []
    
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        
        request_col = None
        notes_col = None
        objection_cols = []
        
        for col in fieldnames:
            if is_request_column(col):
                request_col = col
            elif is_notes_column(col):
                notes_col = col
            else:
                canonical = normalize_column_name(col)
                if canonical:
                    objection_cols.append((col, canonical))
        
        if not request_col:
            raise ValueError(f"Could not find request number column. Columns: {fieldnames}")
        
        for row in reader:
            req_num = (row.get(request_col) or "").strip()
            if not req_num:
                continue
            
            objections = []
            for orig_col, canonical in objection_cols:
                cell_val = row.get(orig_col, "")
                should_use, cell_notes = parse_matrix_cell(cell_val)
                if should_use:
                    objections.append((canonical, cell_notes))
            
            notes_val = (row.get(notes_col) or "").strip() if notes_col else ""
            rows.append({
                "request": req_num,
                "objections": objections,
                "notes_col": notes_val
            })
    
    return rows


def detect_discovery_type(filename):
    """Detect discovery type from filename."""
    name_lower = filename.lower()
    patterns = [
        (r"rfa|request.*admission", "RFA"),
        (r"frog|form.*rog|form.*interrog", "FROG"),
        (r"srog|spec.*rog|special.*interrog", "SROG"),
        (r"rpd|rfp|request.*production", "RPD"),
    ]
    for pattern, dtype in patterns:
        if re.search(pattern, name_lower):
            return dtype
    return "DISCOVERY"


# =============================================================================
# PROMPT GENERATION
# =============================================================================

def load_text_file(path):
    """Load text file if exists."""
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def generate_prompt_package(discovery_path, matrix_path, explanation_temp, output_path):
    """Generate prompt package for OBJECTIONS ONLY (not substantive responses)."""
    dtype = detect_discovery_type(discovery_path.name)
    requests = parse_discovery_file_flexible(discovery_path)
    matrix_data = parse_matrix_flexible(matrix_path)
    objection_lang = load_text_file(OBJECTION_LANG_FILE)
    preliminary_obj = load_text_file(PRELIMINARY_OBJ_FILE)
    case_summary = load_text_file(CASE_SUMMARY_FILE) if explanation_temp >= 3 else ""
    
    lines = []
    
    # === HEADER ===
    lines.append(f"# OBJECTION DRAFTING PACKAGE: {dtype}")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Working Directory:** `{BASE_DIR}`")
    lines.append(f"**Discovery File:** `{discovery_path.name}`")
    lines.append(f"**Matrix File:** `{matrix_path.name}`")
    lines.append(f"**Explanation Level:** {TEMP_LEVELS[explanation_temp][0]}")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # === SCOPE ===
    lines.append("## SCOPE")
    lines.append("")
    lines.append("**Draft OBJECTIONS ONLY.** Do not draft substantive responses.")
    lines.append("")
    lines.append("For each discovery request below, draft the specific objection prose based on")
    lines.append("the marked objection types. The attorney will separately handle substantive responses.")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # === INSTRUCTIONS ===
    lines.append("## DRAFTING RULES")
    lines.append("")
    lines.append("1. **Use the APPROVED TEMPLATES** as your foundation (see below)")
    lines.append("2. **Fill in [SPECIFY] placeholders** with terms from the request")
    lines.append("3. **Combine multiple objections** into flowing prose—no bullets in output")
    lines.append("4. **If no objections marked**, output: `No specific objections.`")
    lines.append("")
    
    # Explanation depth guidance
    lines.append("### Explanation Depth")
    temp_name, temp_desc = TEMP_LEVELS[explanation_temp]
    lines.append(f"**{temp_name.upper()}:** {temp_desc}")
    lines.append("")
    if explanation_temp == 0:
        lines.append("Use template language exactly. Do not add reasoning.")
    elif explanation_temp >= 1:
        lines.append("You may add brief case-specific reasoning where cell notes or the Notes column provide guidance.")
    if explanation_temp >= 3:
        lines.append("Draw from the Case Summary for strategic context.")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # === CASE SUMMARY (if high temp) ===
    if case_summary:
        lines.append("## CASE SUMMARY")
        lines.append("")
        lines.append("Use for context when crafting case-specific reasoning.")
        lines.append("")
        lines.append("```")
        lines.append(case_summary[:6000] + ("\n[...truncated...]" if len(case_summary) > 6000 else ""))
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")
    
    # === PRELIMINARY OBJECTIONS (reference only) ===
    if preliminary_obj:
        lines.append("## PRELIMINARY STATEMENT & GENERAL OBJECTIONS (Reference)")
        lines.append("")
        lines.append("These are incorporated by reference in the final document. Review to understand")
        lines.append("what's already covered at the general level. Your drafted objections are the")
        lines.append("**specific** objections that supplement these general ones.")
        lines.append("")
        lines.append("```")
        lines.append(preliminary_obj)
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")
    
    # === APPROVED TEMPLATES ===
    if objection_lang:
        lines.append("## APPROVED OBJECTION TEMPLATES")
        lines.append("")
        lines.append("Use these as your foundation. Each is numbered for reference.")
        lines.append("")
        lines.append("```")
        lines.append(objection_lang)
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")
    
    # === REQUESTS ===
    lines.append(f"## REQUESTS TO DRAFT ({len(matrix_data)} total)")
    lines.append("")
    
    for item in matrix_data:
        req_num = item["request"]
        objections = item["objections"]
        notes_col = item["notes_col"]
        req_text = requests.get(req_num, "[REQUEST TEXT NOT FOUND]")
        
        lines.append(f"### {dtype} NO. {req_num}")
        lines.append("")
        lines.append("**REQUEST:**")
        lines.append(f"> {req_text[:800]}{'...' if len(req_text) > 800 else ''}")
        lines.append("")
        
        if objections:
            obj_display = []
            for canonical, cell_notes in objections:
                tpl = CANONICAL_TO_TEMPLATE.get(canonical, "?")
                if cell_notes and explanation_temp >= 1:
                    obj_display.append(f"- {canonical} (#{tpl}): *{cell_notes}*")
                else:
                    obj_display.append(f"- {canonical} (#{tpl})")
            lines.append("**OBJECTIONS TO DRAFT:**")
            lines.extend(obj_display)
        else:
            lines.append("**OBJECTIONS TO DRAFT:** None")
        lines.append("")
        
        if notes_col and explanation_temp >= 2:
            lines.append(f"**NOTES:** {notes_col}")
            lines.append("")
        
        lines.append("**DRAFT:**")
        lines.append("```")
        lines.append("[YOUR OBJECTION PROSE HERE]")
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")
    
    # === OUTPUT FORMAT ===
    lines.append("## OUTPUT FORMAT")
    lines.append("")
    lines.append("For each request, provide ONLY the objection prose. Example:")
    lines.append("")
    lines.append("```")
    lines.append(f"### {dtype} NO. 1.1")
    lines.append("")
    lines.append("Responding Party objects to this interrogatory on the grounds that it is vague")
    lines.append("and ambiguous as to the term \"INCIDENT,\" which is defined to span over a decade")
    lines.append("of project history. Responding Party further objects on the grounds that the")
    lines.append("interrogatory is overbroad and unduly burdensome in scope.")
    lines.append("```")
    lines.append("")
    lines.append("Do NOT include:")
    lines.append("- Incorporation language (attorney adds this)")
    lines.append("- Substantive responses (attorney handles separately)")
    lines.append("- \"Subject to and without waiving...\" transitions")
    lines.append("")
    
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return len(matrix_data), sum(1 for m in matrix_data if m["objections"])


# =============================================================================
# GUI
# =============================================================================

class DiscoveryGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Discovery Objections Manager v3.1")
        self.root.geometry("950x750")
        self.root.minsize(850, 650)
        
        self.pairs = []
        self.explanation_temp_var = tk.IntVar(value=2)
        
        self.create_widgets()
        self.scan_for_files()
    
    def create_widgets(self):
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        gen_frame = ttk.Frame(notebook, padding="10")
        notebook.add(gen_frame, text="Generate Prompts")
        self.create_generation_tab(gen_frame)
        
        sync_frame = ttk.Frame(notebook, padding="10")
        notebook.add(sync_frame, text="Sync & State")
        self.create_sync_tab(sync_frame)
        
        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill=tk.X, padx=5, pady=2)
        self.status_label = ttk.Label(status_frame, text="Ready", foreground="gray")
        self.status_label.pack(side=tk.LEFT)
        ttk.Label(status_frame, text=f"📁 {BASE_DIR}", foreground="gray").pack(side=tk.RIGHT)
    
    def create_generation_tab(self, parent):
        # === Support Files Status ===
        support_frame = ttk.LabelFrame(parent, text="Support Files", padding="5")
        support_frame.pack(fill=tk.X, pady=(0, 10))
        
        files_status = []
        for name, path in [("case_summary.txt", CASE_SUMMARY_FILE), 
                           ("preliminary_objections.txt", PRELIMINARY_OBJ_FILE),
                           ("objection_language.txt", OBJECTION_LANG_FILE)]:
            status = "✓" if path.exists() else "✗"
            color = "green" if path.exists() else "red"
            files_status.append((name, status, color))
        
        for i, (name, status, color) in enumerate(files_status):
            lbl = ttk.Label(support_frame, text=f"{status} {name}", foreground=color)
            lbl.pack(side=tk.LEFT, padx=10)
        
        # === Pairs Frame ===
        pairs_frame = ttk.LabelFrame(parent, text="Discovery / Matrix Pairs", padding="10")
        pairs_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        cols = ("discovery", "matrix", "type", "status")
        self.pairs_tree = ttk.Treeview(pairs_frame, columns=cols, show="headings", height=6)
        self.pairs_tree.heading("discovery", text="Discovery File")
        self.pairs_tree.heading("matrix", text="Matrix File")
        self.pairs_tree.heading("type", text="Type")
        self.pairs_tree.heading("status", text="Status")
        self.pairs_tree.column("discovery", width=250)
        self.pairs_tree.column("matrix", width=250)
        self.pairs_tree.column("type", width=80)
        self.pairs_tree.column("status", width=100)
        self.pairs_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scroll = ttk.Scrollbar(pairs_frame, orient=tk.VERTICAL, command=self.pairs_tree.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.pairs_tree.configure(yscrollcommand=scroll.set)
        
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill=tk.X, pady=5)
        
        ttk.Button(btn_frame, text="➕ Add Pair", command=self.add_pair).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="➖ Remove Selected", command=self.remove_pair).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="🔍 Auto-Scan Folder", command=self.scan_for_files).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="🗑️ Clear All", command=self.clear_pairs).pack(side=tk.LEFT, padx=2)
        
        # === Temperature Frame ===
        temp_frame = ttk.LabelFrame(parent, text="Explanation Depth (Temperature)", padding="10")
        temp_frame.pack(fill=tk.X, pady=(0, 10))
        
        slider_row = ttk.Frame(temp_frame)
        slider_row.pack(fill=tk.X)
        ttk.Label(slider_row, text="0 - Minimal").pack(side=tk.LEFT)
        self.temp_scale = ttk.Scale(slider_row, from_=0, to=3, orient=tk.HORIZONTAL,
                                    variable=self.explanation_temp_var, command=self.on_temp_change)
        self.temp_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        ttk.Label(slider_row, text="3 - Full").pack(side=tk.LEFT)
        
        self.temp_desc_label = ttk.Label(temp_frame, text="", wraplength=700, foreground="blue")
        self.temp_desc_label.pack(fill=tk.X, pady=(5, 0))
        self.on_temp_change(None)
        
        # === Generate Button ===
        gen_btn_frame = ttk.Frame(parent)
        gen_btn_frame.pack(fill=tk.X, pady=5)
        
        ttk.Button(gen_btn_frame, text="🚀 Generate All Prompts", 
                   command=self.generate_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(gen_btn_frame, text="📂 Open Folder", 
                   command=self.open_folder).pack(side=tk.LEFT, padx=2)
        
        # === Output ===
        output_frame = ttk.LabelFrame(parent, text="Output Log", padding="5")
        output_frame.pack(fill=tk.BOTH, expand=True)
        
        self.output_text = scrolledtext.ScrolledText(
            output_frame, wrap=tk.WORD, font=("Consolas", 10),
            bg="#1e1e1e", fg="#d4d4d4", height=10
        )
        self.output_text.pack(fill=tk.BOTH, expand=True)
    
    def create_sync_tab(self, parent):
        btn_frame = ttk.LabelFrame(parent, text="Actions", padding="10")
        btn_frame.pack(fill=tk.X, pady=(0, 10))
        
        row1 = ttk.Frame(btn_frame)
        row1.pack(fill=tk.X, pady=2)
        for text, cmd in [("🔍 Check", self.cmd_check), ("📝 Diff", self.cmd_diff),
                          ("📷 Snapshot", self.cmd_snapshot), ("✅ Apply", self.cmd_apply)]:
            ttk.Button(row1, text=text, command=cmd, width=15).pack(side=tk.LEFT, padx=2)
        
        row2 = ttk.Frame(btn_frame)
        row2.pack(fill=tk.X, pady=2)
        for text, cmd in [("📊 Status", self.cmd_status), ("📜 History", self.cmd_history),
                          ("🔄 Init", self.cmd_init)]:
            ttk.Button(row2, text=text, command=cmd, width=15).pack(side=tk.LEFT, padx=2)
        
        output_frame = ttk.LabelFrame(parent, text="Output", padding="5")
        output_frame.pack(fill=tk.BOTH, expand=True)
        
        self.sync_output = scrolledtext.ScrolledText(
            output_frame, wrap=tk.WORD, font=("Consolas", 10),
            bg="#1e1e1e", fg="#d4d4d4"
        )
        self.sync_output.pack(fill=tk.BOTH, expand=True)
    
    # === Pair Management ===
    
    def scan_for_files(self):
        """Auto-scan folder for discovery/matrix pairs."""
        self.clear_pairs()
        
        txt_files = [f for f in BASE_DIR.glob("*.txt") 
                     if f.name.lower() not in SKIP_TXT_FILES]
        
        csv_files = []
        for f in BASE_DIR.glob("*.csv"):
            try:
                with open(f, newline="", encoding="utf-8-sig") as csvfile:
                    reader = csv.DictReader(csvfile)
                    if reader.fieldnames:
                        for col in reader.fieldnames:
                            if is_request_column(col):
                                csv_files.append(f)
                                break
            except:
                continue
        
        matched_csvs = set()
        for txt in txt_files:
            txt_base = txt.stem.lower().replace("_", "").replace("-", "").replace(" ", "")
            best_match = None
            best_score = 0
            
            for csv_f in csv_files:
                if csv_f in matched_csvs:
                    continue
                csv_base = csv_f.stem.lower().replace("_", "").replace("-", "").replace(" ", "")
                
                score = len(set(txt_base) & set(csv_base))
                if txt_base in csv_base or csv_base in txt_base:
                    score += 10
                
                if score > best_score:
                    best_score = score
                    best_match = csv_f
            
            if best_match:
                self.add_pair_direct(txt, best_match)
                matched_csvs.add(best_match)
        
        self.log(f"Auto-scanned: found {len(self.pairs)} pair(s)")
    
    def add_pair(self):
        disc_path = filedialog.askopenfilename(
            title="Select Discovery Request File",
            initialdir=str(BASE_DIR),
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if not disc_path:
            return
        
        matrix_path = filedialog.askopenfilename(
            title="Select Objection Matrix File",
            initialdir=str(BASE_DIR),
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if not matrix_path:
            return
        
        self.add_pair_direct(Path(disc_path), Path(matrix_path))
    
    def add_pair_direct(self, disc_path, matrix_path):
        dtype = detect_discovery_type(disc_path.name)
        self.pairs.append((disc_path, matrix_path))
        self.pairs_tree.insert("", tk.END, values=(
            disc_path.name, matrix_path.name, dtype, "Ready"
        ))
    
    def remove_pair(self):
        selected = self.pairs_tree.selection()
        if not selected:
            return
        
        for item in selected:
            idx = self.pairs_tree.index(item)
            self.pairs_tree.delete(item)
            if idx < len(self.pairs):
                del self.pairs[idx]
    
    def clear_pairs(self):
        self.pairs.clear()
        for item in self.pairs_tree.get_children():
            self.pairs_tree.delete(item)
    
    # === Generation ===
    
    def on_temp_change(self, value):
        temp = int(self.explanation_temp_var.get())
        name, desc = TEMP_LEVELS[temp]
        self.temp_desc_label.config(text=f"Level {temp} ({name}): {desc}")
    
    def generate_all(self):
        if not self.pairs:
            messagebox.showwarning("No Pairs", "Add at least one discovery/matrix pair first.")
            return
        
        self.output_text.delete(1.0, tk.END)
        temp = int(self.explanation_temp_var.get())
        
        results = []
        for i, (disc_path, matrix_path) in enumerate(self.pairs):
            item_id = self.pairs_tree.get_children()[i]
            
            try:
                dtype = detect_discovery_type(disc_path.name)
                timestamp = datetime.now().strftime("%H%M%S")
                output_name = f"prompt_{dtype}_{disc_path.stem}_{timestamp}.md"
                output_path = BASE_DIR / output_name
                
                total, with_obj = generate_prompt_package(disc_path, matrix_path, temp, output_path)
                
                self.pairs_tree.set(item_id, "status", f"✓ {total} reqs")
                results.append((output_name, total, with_obj, None))
                
            except Exception as e:
                self.pairs_tree.set(item_id, "status", "❌ Error")
                results.append((disc_path.name, 0, 0, str(e)))
        
        self.log("=" * 50)
        self.log(f"GENERATION COMPLETE - {len(results)} file(s)")
        self.log("=" * 50)
        
        for output_name, total, with_obj, error in results:
            if error:
                self.log(f"❌ {output_name}: {error}")
            else:
                self.log(f"✓ {output_name}: {total} requests, {with_obj} with objections")
        
        self.log("")
        self.log("Generated prompts include:")
        self.log("  - Case summary (for context)")
        self.log("  - Preliminary objections (incorporated by reference)")
        self.log("  - Approved objection templates")
        self.log("")
        self.log("Files saved to working directory.")
        self.status_label.config(text=f"Generated {len([r for r in results if not r[3]])} prompt(s)")
    
    def log(self, msg):
        self.output_text.insert(tk.END, msg + "\n")
        self.output_text.see(tk.END)
    
    def open_folder(self):
        import os
        os.startfile(str(BASE_DIR))
    
    # === Sync Commands ===
    
    def run_sync_cmd(self, args, desc):
        self.sync_output.delete(1.0, tk.END)
        self.sync_output.insert(tk.END, f">>> {desc}\n\n")
        self.status_label.config(text=f"Running: {desc}...")
        
        def run():
            try:
                result = subprocess.run(
                    [sys.executable, str(SMART_SYNC)] + args,
                    capture_output=True, text=True, cwd=str(BASE_DIR)
                )
                self.root.after(0, lambda: self.sync_output.insert(tk.END, result.stdout + result.stderr))
                self.root.after(0, lambda: self.status_label.config(text=f"Done: {desc}"))
            except Exception as e:
                self.root.after(0, lambda: self.sync_output.insert(tk.END, f"Error: {e}"))
        
        threading.Thread(target=run).start()
    
    def cmd_check(self): self.run_sync_cmd(["--check"], "Check")
    def cmd_diff(self): self.run_sync_cmd(["--diff"], "Diff")
    def cmd_status(self): self.run_sync_cmd(["--status"], "Status")
    def cmd_history(self): self.run_sync_cmd(["--history"], "History")
    
    def cmd_snapshot(self):
        from tkinter import simpledialog
        note = simpledialog.askstring("Note", "Snapshot note (optional):", parent=self.root)
        if note is None: return
        self.run_sync_cmd(["--snapshot"] + ([note] if note else []), "Snapshot")
    
    def cmd_apply(self):
        r = messagebox.askyesnocancel("Apply", "Use default file?\n\nYes=Default, No=Browse")
        if r is None: return
        if r:
            self.run_sync_cmd(["--apply"], "Apply")
        else:
            f = filedialog.askopenfilename(initialdir=str(BASE_DIR), filetypes=[("MD", "*.md")])
            if f: self.run_sync_cmd(["--apply", f], "Apply")
    
    def cmd_init(self):
        if messagebox.askyesno("Init", "Reset baseline?"):
            self.run_sync_cmd(["--init"], "Init")


def main():
    root = tk.Tk()
    app = DiscoveryGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
