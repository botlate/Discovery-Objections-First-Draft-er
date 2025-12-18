#!/usr/bin/env python3
"""
Discovery Objections - Prompt Package Generator v3.1
====================================================

Standalone script for generating AI prompt packages with flexible parsing.

Features:
- Flexible discovery format detection (Form Interrogatory, RFA, RPD, SROG, etc.)
- Dynamic column detection (works with any matrix column names)
- Cell content parsing (any content = use; "x; notes" extracts notes)
- Configurable explanation temperature
- Includes case summary and preliminary objections
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

# Explanation levels
TEMP_LEVELS = {
    0: ("Minimal", "Use approved templates only. No case-specific reasoning."),
    1: ("Low", "Add brief reasoning from cell notes only (1 sentence max)."),
    2: ("Medium", "Add reasoning from cell notes and Notes/comments column (1-2 sentences)."),
    3: ("High", "Full reasoning from case summary, notes, and comments (2-3 sentences)."),
}

# Skip these txt files when scanning for discovery
SKIP_TXT_FILES = {"case_summary.txt", "objection_language.txt", "preliminary_objections.txt"}


# =============================================================================
# FLEXIBLE PARSING
# =============================================================================

def normalize_column_name(col_name):
    """Convert column name to canonical form, or return original if unknown."""
    if not col_name:
        return None
    lower = col_name.strip().lower()
    return ALIAS_TO_CANONICAL.get(lower, col_name)


def is_notes_column(col_name):
    """Check if column is notes/comments."""
    if not col_name:
        return False
    lower = col_name.strip().lower()
    return lower in ("notes", "comments", "note", "comment", "remarks")


def is_request_column(col_name):
    """Check if column is request number."""
    if not col_name:
        return False
    lower = col_name.strip().lower()
    return lower in ("request", "req", "no", "no.", "number", "request no", "request no.", 
                     "interrogatory", "rog", "rfa", "rpd")


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


def parse_discovery_file(filepath):
    """
    Flexibly parse discovery requests from various formats.
    Returns {request_num: text}
    """
    content = filepath.read_text(encoding="utf-8")
    requests = {}
    
    # Pattern 1: "Form Interrogatory No. X.X" (with optional quotes)
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
    
    # Pattern 5: Bare "X.X" at start of line
    for match in re.finditer(
        r'^(\d+\.\d+)\s+(.*?)(?=^\d+\.\d+\s|\Z)',
        content, re.MULTILINE | re.DOTALL
    ):
        text = match.group(2).strip()
        if len(text) > 20:
            requests[match.group(1)] = text
    
    return requests


def parse_matrix_cell(cell_value):
    """
    Parse matrix cell.
    Returns: (should_use: bool, notes: str or None)
    
    Rules:
    - Empty = don't use
    - Any content = use
    - "x" alone = use, no notes
    - "x; notes" = use, with notes
    - "other text" = use, text becomes notes
    """
    if not cell_value:
        return (False, None)
    
    val = str(cell_value).strip()
    if not val:
        return (False, None)
    
    # "x; notes" pattern
    if ";" in val:
        parts = val.split(";", 1)
        marker = parts[0].strip().upper()
        notes = parts[1].strip() if len(parts) > 1 else None
        return (True, notes if notes else None)
    
    # Bare markers
    if val.upper() in ("X", "YES", "Y", "1", "TRUE"):
        return (True, None)
    
    # Any other content = use with content as notes
    return (True, val)


def parse_matrix(csv_path):
    """
    Flexibly parse CSV matrix, auto-detecting column purposes.
    Returns: [{"request": str, "objections": [(canonical_name, cell_notes), ...], "notes_col": str}, ...]
    """
    rows = []
    
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        
        # Identify columns
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
            raise ValueError(f"No request number column found. Columns: {fieldnames}")
        
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


# =============================================================================
# FILE DISCOVERY
# =============================================================================

def find_discovery_files():
    """Find potential discovery request files."""
    return [f for f in BASE_DIR.glob("*.txt") if f.name.lower() not in SKIP_TXT_FILES]


def find_matrix_files():
    """Find CSV files with a Request column."""
    files = []
    for f in BASE_DIR.glob("*.csv"):
        try:
            with open(f, newline="", encoding="utf-8-sig") as csvfile:
                reader = csv.DictReader(csvfile)
                if reader.fieldnames:
                    for col in reader.fieldnames:
                        if is_request_column(col):
                            files.append(f)
                            break
        except:
            continue
    return files


def auto_match_pairs():
    """Auto-match discovery files with matrix files by name similarity."""
    txt_files = find_discovery_files()
    csv_files = find_matrix_files()
    
    pairs = []
    matched_csvs = set()
    
    for txt in txt_files:
        txt_base = txt.stem.lower().replace("_", "").replace("-", "").replace(" ", "")
        best_match = None
        best_score = 0
        
        for csv_f in csv_files:
            if csv_f in matched_csvs:
                continue
            csv_base = csv_f.stem.lower().replace("_", "").replace("-", "").replace(" ", "")
            
            # Overlap scoring
            score = len(set(txt_base) & set(csv_base))
            if txt_base in csv_base or csv_base in txt_base:
                score += 10
            
            if score > best_score:
                best_score = score
                best_match = csv_f
        
        if best_match and best_score > 3:
            pairs.append((txt, best_match))
            matched_csvs.add(best_match)
    
    return pairs


# =============================================================================
# PROMPT GENERATION
# =============================================================================

def load_text_file(path):
    """Load text file if exists."""
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def generate_prompt_package(discovery_path, matrix_path, explanation_temp, output_path):
    """
    Generate prompt package.
    Returns: (total_requests, requests_with_objections)
    """
    dtype = detect_discovery_type(discovery_path.name)
    requests = parse_discovery_file(discovery_path)
    matrix_data = parse_matrix(matrix_path)
    objection_lang = load_text_file(OBJECTION_LANG_FILE)
    preliminary_obj = load_text_file(PRELIMINARY_OBJ_FILE)
    case_summary = load_text_file(CASE_SUMMARY_FILE)
    
    noun_map = {"RFA": "request", "FROG": "interrogatory", "SROG": "interrogatory", "RPD": "request"}
    noun = noun_map.get(dtype, "request")
    
    lines = []
    
    # === HEADER ===
    lines.append(f"# PROMPT PACKAGE: {dtype}")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Working Directory:** `{BASE_DIR}`")
    lines.append(f"**Discovery File:** `{discovery_path.name}`")
    lines.append(f"**Matrix File:** `{matrix_path.name}`")
    lines.append(f"**Explanation Level:** {TEMP_LEVELS[explanation_temp][0]}")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # === SETUP INSTRUCTIONS ===
    lines.append("## SETUP & CONTEXT")
    lines.append("")
    lines.append(f"**Working Folder:** `{BASE_DIR}`")
    lines.append("")
    lines.append("Before drafting responses, review the following context documents in the working folder:")
    lines.append("")
    if case_summary:
        lines.append(f"- **Case Summary:** `{CASE_SUMMARY_FILE.name}` — Understanding the case context helps craft persuasive, case-specific objections.")
    if preliminary_obj:
        lines.append(f"- **Preliminary Objections:** `{PRELIMINARY_OBJ_FILE.name}` — Every response incorporates these by reference.")
    if objection_lang:
        lines.append(f"- **Objection Templates:** `{OBJECTION_LANG_FILE.name}` — Approved language for specific objections.")
    lines.append("")
    lines.append("These documents are included below for your reference.")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # === INSTRUCTIONS ===
    lines.append("## DRAFTING INSTRUCTIONS")
    lines.append("")
    lines.append(f"Draft {dtype} responses using the **JT three-layer format**.")
    lines.append(f"Use **\"{noun}\"** as the discovery type (not \"request\" generically).")
    lines.append("")
    lines.append("### STRUCTURE (every response MUST follow)")
    lines.append("```")
    lines.append("Responding Party incorporates by reference the Preliminary Statement and General")
    lines.append("Objections, above, as if fully set forth herein.")
    lines.append("")
    lines.append("[SPECIFIC OBJECTIONS - if any marked, as flowing prose]")
    lines.append("")
    lines.append("Subject to, and without waiving, the Preliminary Statement, General Objections,")
    lines.append("and the foregoing objections, Responding Party responds as follows:")
    lines.append("")
    lines.append("[SUBSTANTIVE RESPONSE]")
    lines.append("```")
    lines.append("")
    
    # === EXPLANATION DEPTH ===
    lines.append("### EXPLANATION DEPTH")
    temp_name, temp_desc = TEMP_LEVELS[explanation_temp]
    lines.append(f"**{temp_name.upper()}:** {temp_desc}")
    lines.append("")
    if explanation_temp >= 2:
        lines.append("When adding case-specific reasoning:")
        lines.append("- Draw from the Case Summary for strategic context")
        lines.append("- Use cell notes (shown with each objection) for specific guidance")
        lines.append("- Reference the Notes column for request-level context")
        lines.append("- Keep reasoning concise (1-3 sentences per objection ground)")
        lines.append("")
    lines.append("---")
    lines.append("")
    
    # === CASE SUMMARY ===
    if case_summary:
        lines.append("## CASE SUMMARY")
        lines.append("")
        lines.append("Review this summary to understand the case context and craft persuasive objections.")
        lines.append("")
        lines.append("```")
        if len(case_summary) > 6000:
            lines.append(case_summary[:6000])
            lines.append("\n[...truncated for length...]")
        else:
            lines.append(case_summary)
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")
    
    # === PRELIMINARY OBJECTIONS ===
    if preliminary_obj:
        lines.append("## PRELIMINARY STATEMENT & GENERAL OBJECTIONS")
        lines.append("")
        lines.append("These are incorporated by reference in every response. Review them to understand")
        lines.append("what grounds are already preserved at the general level.")
        lines.append("")
        lines.append("```")
        lines.append(preliminary_obj)
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")
    
    # === OBJECTION LANGUAGE ===
    if objection_lang:
        lines.append("## APPROVED OBJECTION TEMPLATES")
        lines.append("")
        lines.append("Use these numbered templates as your foundation. Fill in [SPECIFY] placeholders.")
        lines.append("Combine multiple objections into flowing prose (no bullet points in final response).")
        lines.append("")
        lines.append("```")
        lines.append(objection_lang)
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")
    
    # === REQUESTS ===
    lines.append(f"## REQUESTS ({len(matrix_data)} total)")
    lines.append("")
    
    for item in matrix_data:
        req_num = item["request"]
        objections = item["objections"]
        notes_col = item["notes_col"]
        req_text = requests.get(req_num, "[REQUEST TEXT NOT FOUND IN DISCOVERY FILE]")
        
        lines.append(f"### {dtype} NO. {req_num}")
        lines.append("")
        lines.append("**TEXT:**")
        lines.append(f"> {req_text[:800]}{'...' if len(req_text) > 800 else ''}")
        lines.append("")
        
        if objections:
            obj_display = []
            for canonical, cell_notes in objections:
                tpl = CANONICAL_TO_TEMPLATE.get(canonical, "?")
                if tpl == "?":
                    # Unknown objection type - still include but flag it
                    obj_display.append(f"- **{canonical}** (custom): *{cell_notes}*" if cell_notes else f"- **{canonical}** (custom)")
                elif cell_notes and explanation_temp >= 1:
                    obj_display.append(f"- **{canonical}** (Template #{tpl}): *{cell_notes}*")
                else:
                    obj_display.append(f"- **{canonical}** (Template #{tpl})")
            
            lines.append("**OBJECTIONS:**")
            lines.extend(obj_display)
        else:
            lines.append("**OBJECTIONS:** None (still use incorporation language)")
        lines.append("")
        
        if notes_col and explanation_temp >= 2:
            lines.append(f"**NOTES:** {notes_col}")
            lines.append("")
        
        lines.append("---")
        lines.append("")
    
    # === OUTPUT FORMAT ===
    lines.append("## OUTPUT FORMAT")
    lines.append("")
    lines.append("Save your output as a `.md` file with this structure for each request:")
    lines.append("")
    lines.append("```")
    lines.append(f"### {dtype} NO. [NUMBER]")
    lines.append("")
    lines.append("Responding Party incorporates by reference the Preliminary Statement and General")
    lines.append("Objections, above, as if fully set forth herein.")
    lines.append("")
    lines.append("[Specific objections as flowing prose - if any]")
    lines.append("")
    lines.append("Subject to, and without waiving, the Preliminary Statement, General Objections,")
    lines.append("and the foregoing objections, Responding Party responds as follows:")
    lines.append("")
    lines.append("[Substantive response]")
    lines.append("")
    lines.append("---")
    lines.append("```")
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
    parser.add_argument("--output", "-o", type=str, help="Output filename (auto-generated if not specified)")
    parser.add_argument("--list", "-l", action="store_true", help="List auto-detected pairs and exit")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("DISCOVERY OBJECTIONS - PROMPT PACKAGE GENERATOR v3.1")
    print("=" * 60)
    print(f"Working directory: {BASE_DIR}")
    print()
    
    # List mode
    if args.list:
        pairs = auto_match_pairs()
        print(f"Auto-detected {len(pairs)} discovery/matrix pair(s):\n")
        for disc, matrix in pairs:
            dtype = detect_discovery_type(disc.name)
            print(f"  [{dtype}] {disc.name} <-> {matrix.name}")
        
        print("\nAvailable discovery files:")
        for f in find_discovery_files():
            print(f"  - {f.name}")
        
        print("\nAvailable matrix files:")
        for f in find_matrix_files():
            print(f"  - {f.name}")
        
        print("\nSupport files:")
        print(f"  - case_summary.txt: {'Found' if CASE_SUMMARY_FILE.exists() else 'NOT FOUND'}")
        print(f"  - preliminary_objections.txt: {'Found' if PRELIMINARY_OBJ_FILE.exists() else 'NOT FOUND'}")
        print(f"  - objection_language.txt: {'Found' if OBJECTION_LANG_FILE.exists() else 'NOT FOUND'}")
        return
    
    # Determine pairs to process
    if args.discovery and args.matrix:
        disc_path = BASE_DIR / args.discovery
        matrix_path = BASE_DIR / args.matrix
        
        if not disc_path.exists():
            print(f"ERROR: Discovery file not found: {disc_path}")
            sys.exit(1)
        if not matrix_path.exists():
            print(f"ERROR: Matrix file not found: {matrix_path}")
            sys.exit(1)
        
        pairs = [(disc_path, matrix_path)]
    else:
        pairs = auto_match_pairs()
        if not pairs:
            print("No discovery/matrix pairs found.")
            print("Use --discovery and --matrix to specify files manually,")
            print("or use --list to see available files.")
            sys.exit(1)
    
    print(f"Explanation level: {args.temp} ({TEMP_LEVELS[args.temp][0]})")
    print(f"Processing {len(pairs)} pair(s)...\n")
    
    # Generate
    results = []
    for disc_path, matrix_path in pairs:
        dtype = detect_discovery_type(disc_path.name)
        
        if args.output and len(pairs) == 1:
            output_path = BASE_DIR / args.output
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_name = f"prompt_{dtype}_{disc_path.stem}_{timestamp}.md"
            output_path = BASE_DIR / output_name
        
        try:
            total, with_obj = generate_prompt_package(disc_path, matrix_path, args.temp, output_path)
            results.append((output_path.name, disc_path.name, matrix_path.name, total, with_obj, None))
            print(f"  ✓ {output_path.name}")
            print(f"    {total} requests, {with_obj} with objections")
        except Exception as e:
            results.append((None, disc_path.name, matrix_path.name, 0, 0, str(e)))
            print(f"  ✗ {disc_path.name}: {e}")
        print()
    
    # Summary
    print("=" * 60)
    success = sum(1 for r in results if r[5] is None)
    print(f"Generated {success}/{len(results)} prompt package(s)")
    print()
    print("NEXT STEPS:")
    print("1. Give the prompt_*.md file to any AI")
    print("2. AI drafts responses using JT three-layer format")
    print("3. Review and finalize")
    print("=" * 60)


if __name__ == "__main__":
    main()
