#!/usr/bin/env python3
"""
Discovery Objections - Prompt Package Generator v3.2
====================================================

Generates AI prompt packages for drafting OBJECTIONS ONLY.
Does NOT draft substantive responses—that requires underlying case information.

Features:
- Flexible discovery format detection
- Dynamic column detection (works with any matrix column names)
- Cell content parsing (any content = use; "x; notes" extracts notes)
- Configurable explanation depth
- Batch processing of multiple discovery/matrix pairs

Usage:
    python generate_prompt_packages.py                          # Auto-scan and generate all
    python generate_prompt_packages.py --discovery FILE --matrix FILE   # Specific pair
    python generate_prompt_packages.py --temp 3                 # Set explanation level (0-3)
    python generate_prompt_packages.py --list                   # List detected pairs
"""

import argparse
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

# =============================================================================
# CONFIGURATION
# =============================================================================

BASE_DIR = Path(__file__).parent.resolve()
CASE_SUMMARY_FILE = BASE_DIR / "case_summary.txt"
OBJECTION_LANG_FILE = BASE_DIR / "objection_language.txt"
PRELIMINARY_OBJ_FILE = BASE_DIR / "preliminary_objections.txt"

# Known objection column aliases
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
    "Relevance": "1", "Compound": "2", "Vague": "3", "Speculation": "4",
    "Assumes Facts": "5", "Expert Opinion": "6", "Legal Conclusion": "7",
    "Overbroad": "8", "Duplicative": "9", "ESI-Burden": "10", "Oppressive": "11",
    "Not-Complete": "12", "Annoyance": "13", "Equally-Avail": "14", "Public-Domain": "15",
    "Atty-Client": "16", "Work-Product": "17", "Privacy-RP": "18", "Privacy-3rd": "19",
    "Joint-Defense": "20", "Anticipation": "21", "Premature": "22",
    "Settlement-Priv": "23", "Def-Overbroad": "24",
}

# Explanation levels
TEMP_LEVELS = {
    0: ("Minimal", "Use approved templates verbatim. No case-specific reasoning."),
    1: ("Low", "Add brief reasoning from cell notes only (1 sentence max)."),
    2: ("Medium", "Add reasoning from cell notes and Notes column (1-2 sentences)."),
    3: ("High", "Full case-specific reasoning from case summary and notes (2-3 sentences)."),
}

SKIP_TXT_FILES = {"case_summary.txt", "objection_language.txt", "preliminary_objections.txt"}


# =============================================================================
# PARSING FUNCTIONS
# =============================================================================

def normalize_column_name(col_name):
    if not col_name:
        return None
    lower = col_name.strip().lower()
    return ALIAS_TO_CANONICAL.get(lower, col_name)

def is_notes_column(col_name):
    if not col_name:
        return False
    return col_name.strip().lower() in ("notes", "comments", "note", "comment", "remarks")

def is_request_column(col_name):
    if not col_name:
        return False
    lower = col_name.strip().lower()
    return lower in ("request", "req", "no", "no.", "number", "request no", 
                     "request no.", "interrogatory", "rog", "rfa", "rpd")

def detect_discovery_type(filename):
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

def parse_discovery_file(filepath):
    """Parse discovery requests. Returns {request_num: text}."""
    content = filepath.read_text(encoding="utf-8")
    requests = {}
    
    # Pattern 1: Form Interrogatory No. X.X
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
    
    # Pattern 2: REQUEST FOR ADMISSION NO. X
    for match in re.finditer(
        r'REQUEST\s+FOR\s+ADMISSION\s+NO\.\s*(\d+)[:\s]+(.*?)(?=REQUEST\s+FOR\s+ADMISSION\s+NO\.|$)',
        content, re.DOTALL | re.IGNORECASE
    ):
        requests[match.group(1)] = match.group(2).strip()
    if requests:
        return requests
    
    # Pattern 3: REQUEST FOR PRODUCTION NO. X
    for match in re.finditer(
        r'REQUEST\s+FOR\s+PRODUCTION\s+(?:OF\s+DOCUMENTS\s+)?NO\.\s*(\d+)[:\s]+(.*?)(?=REQUEST\s+FOR\s+PRODUCTION|$)',
        content, re.DOTALL | re.IGNORECASE
    ):
        requests[match.group(1)] = match.group(2).strip()
    if requests:
        return requests
    
    # Pattern 4: INTERROGATORY NO. X
    for match in re.finditer(
        r'(?:SPECIAL\s+)?INTERROGATORY\s+NO\.\s*(\d+)[:\s]+(.*?)(?=(?:SPECIAL\s+)?INTERROGATORY\s+NO\.|$)',
        content, re.DOTALL | re.IGNORECASE
    ):
        requests[match.group(1)] = match.group(2).strip()
    if requests:
        return requests
    
    # Pattern 5: Bare X.X at start of line
    for match in re.finditer(r'^(\d+\.\d+)\s+(.*?)(?=^\d+\.\d+\s|\Z)', content, re.MULTILINE | re.DOTALL):
        text = match.group(2).strip()
        if len(text) > 20:
            requests[match.group(1)] = text
    
    return requests

def parse_matrix_cell(cell_value):
    """Returns (should_use: bool, notes: str or None)."""
    if not cell_value:
        return (False, None)
    val = str(cell_value).strip()
    if not val:
        return (False, None)
    if ";" in val:
        parts = val.split(";", 1)
        notes = parts[1].strip() if len(parts) > 1 else None
        return (True, notes)
    if val.upper() in ("X", "YES", "Y", "1", "TRUE"):
        return (True, None)
    return (True, val)

def parse_matrix(csv_path):
    """Parse CSV matrix. Returns list of {request, objections, notes_col}."""
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
            raise ValueError(f"No request column found. Columns: {fieldnames}")
        
        for row in reader:
            req_num = (row.get(request_col) or "").strip()
            if not req_num:
                continue
            
            objections = []
            for orig_col, canonical in objection_cols:
                should_use, cell_notes = parse_matrix_cell(row.get(orig_col, ""))
                if should_use:
                    objections.append((canonical, cell_notes))
            
            notes_val = (row.get(notes_col) or "").strip() if notes_col else ""
            rows.append({"request": req_num, "objections": objections, "notes_col": notes_val})
    
    return rows


# =============================================================================
# FILE DISCOVERY
# =============================================================================

def find_discovery_files():
    return [f for f in BASE_DIR.glob("*.txt") if f.name.lower() not in SKIP_TXT_FILES]

def find_matrix_files():
    files = []
    for f in BASE_DIR.glob("*.csv"):
        try:
            with open(f, newline="", encoding="utf-8-sig") as csvfile:
                reader = csv.DictReader(csvfile)
                if reader.fieldnames and any(is_request_column(c) for c in reader.fieldnames):
                    files.append(f)
        except:
            continue
    return files

def auto_match_pairs():
    txt_files = find_discovery_files()
    csv_files = find_matrix_files()
    pairs = []
    matched = set()
    
    for txt in txt_files:
        txt_base = txt.stem.lower().replace("_", "").replace("-", "").replace(" ", "")
        best_match, best_score = None, 0
        
        for csv_f in csv_files:
            if csv_f in matched:
                continue
            csv_base = csv_f.stem.lower().replace("_", "").replace("-", "").replace(" ", "")
            score = len(set(txt_base) & set(csv_base))
            if txt_base in csv_base or csv_base in txt_base:
                score += 10
            if score > best_score:
                best_score, best_match = score, csv_f
        
        if best_match and best_score > 3:
            pairs.append((txt, best_match))
            matched.add(best_match)
    
    return pairs

def load_text_file(path):
    return path.read_text(encoding="utf-8") if path.exists() else ""


# =============================================================================
# PROMPT GENERATION
# =============================================================================

def generate_prompt_package(discovery_path, matrix_path, explanation_temp, output_path):
    """Generate prompt package for OBJECTIONS ONLY."""
    dtype = detect_discovery_type(discovery_path.name)
    requests = parse_discovery_file(discovery_path)
    matrix_data = parse_matrix(matrix_path)
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
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Generate AI prompt packages for discovery objections",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python generate_prompt_packages.py                     # Auto-scan and generate all
  python generate_prompt_packages.py --list              # List detected pairs
  python generate_prompt_packages.py --temp 3            # High explanation level
  python generate_prompt_packages.py --discovery Form_Rogs.txt --matrix form_rogs_matrix.csv
        """
    )
    parser.add_argument("--discovery", "-d", type=str, help="Discovery request file (.txt)")
    parser.add_argument("--matrix", "-m", type=str, help="Objection matrix file (.csv)")
    parser.add_argument("--temp", "-t", type=int, default=2, choices=[0, 1, 2, 3],
                        help="Explanation temperature (0=minimal, 3=full). Default: 2")
    parser.add_argument("--output", "-o", type=str, help="Output filename")
    parser.add_argument("--list", "-l", action="store_true", help="List detected pairs")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("DISCOVERY OBJECTIONS - PROMPT GENERATOR v3.2")
    print("=" * 60)
    print(f"Working directory: {BASE_DIR}")
    print()
    
    if args.list:
        pairs = auto_match_pairs()
        print(f"Auto-detected {len(pairs)} pair(s):\n")
        for disc, matrix in pairs:
            print(f"  [{detect_discovery_type(disc.name)}] {disc.name} <-> {matrix.name}")
        print(f"\nSupport files:")
        print(f"  case_summary.txt: {'Found' if CASE_SUMMARY_FILE.exists() else 'NOT FOUND'}")
        print(f"  preliminary_objections.txt: {'Found' if PRELIMINARY_OBJ_FILE.exists() else 'NOT FOUND'}")
        print(f"  objection_language.txt: {'Found' if OBJECTION_LANG_FILE.exists() else 'NOT FOUND'}")
        return
    
    if args.discovery and args.matrix:
        disc_path = BASE_DIR / args.discovery
        matrix_path = BASE_DIR / args.matrix
        if not disc_path.exists():
            print(f"ERROR: {disc_path} not found"); sys.exit(1)
        if not matrix_path.exists():
            print(f"ERROR: {matrix_path} not found"); sys.exit(1)
        pairs = [(disc_path, matrix_path)]
    else:
        pairs = auto_match_pairs()
        if not pairs:
            print("No pairs found. Use --list or specify --discovery and --matrix.")
            sys.exit(1)
    
    print(f"Explanation level: {args.temp} ({TEMP_LEVELS[args.temp][0]})")
    print(f"Processing {len(pairs)} pair(s)...\n")
    
    for disc_path, matrix_path in pairs:
        dtype = detect_discovery_type(disc_path.name)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_name = args.output if (args.output and len(pairs) == 1) else f"prompt_{dtype}_{disc_path.stem}_{timestamp}.md"
        output_path = BASE_DIR / output_name
        
        try:
            total, with_obj = generate_prompt_package(disc_path, matrix_path, args.temp, output_path)
            print(f"  ✓ {output_name}: {total} requests, {with_obj} with objections")
        except Exception as e:
            print(f"  ✗ {disc_path.name}: {e}")
    
    print()
    print("NEXT STEPS:")
    print("1. Give the prompt_*.md file to your AI")
    print("2. AI drafts objection prose for each request")
    print("3. Attorney reviews, then adds to final response document")


if __name__ == "__main__":
    main()
