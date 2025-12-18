#!/usr/bin/env python3
"""
Discovery Objections - Smart Sync v3.1
======================================

Flexible state tracking and change detection.

Commands:
  --init              Initialize/reset baseline from current files
  --check             Show what changed since baseline
  --diff              Generate edits prompt package
  --apply [FILE]      Apply completed edits to final .md files
  --snapshot [NOTE]   Record current state (audit trail)
  --status            Show baseline info
  --history           Show audit trail

Works with any discovery/matrix file pairs in the folder.
"""

import csv
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

# =============================================================================
# CONFIGURATION
# =============================================================================

BASE_DIR = Path(__file__).parent.resolve()
STATE_FILE = BASE_DIR / "objection_state.json"
OBJECTION_LANG_FILE = BASE_DIR / "objection_language.txt"
CASE_SUMMARY_FILE = BASE_DIR / "case_summary.txt"
EDITS_PACKAGE = BASE_DIR / "edits_prompt_package.md"

# Files to skip when scanning for discovery files
SKIP_TXT_FILES = {"case_summary.txt", "objection_language.txt", "preliminary_objections.txt"}

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def file_hash(path):
    """Generate SHA-256 hash of file contents."""
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]

def file_content(path):
    """Read file contents, return None if not exists."""
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")

def now_iso():
    """Current timestamp in ISO format."""
    return datetime.now().isoformat()

def is_request_column(col_name):
    """Check if column is request number."""
    if not col_name:
        return False
    lower = col_name.strip().lower()
    return lower in ("request", "req", "no", "no.", "number", "request no", 
                     "request no.", "interrogatory", "rog", "rfa", "rpd")

def is_notes_column(col_name):
    """Check if column is notes/comments."""
    if not col_name:
        return False
    lower = col_name.strip().lower()
    return lower in ("notes", "comments", "note", "comment", "remarks")

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
# FILE DISCOVERY
# =============================================================================

def find_discovery_files():
    """Find potential discovery request .txt files."""
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

def find_final_files():
    """Find *_final.md or *_draft.md output files."""
    finals = list(BASE_DIR.glob("*_final.md"))
    drafts = list(BASE_DIR.glob("*_draft.md"))
    responses = list(BASE_DIR.glob("*_responses*.md"))
    return finals + drafts + responses

def auto_match_pairs():
    """Auto-match discovery files with matrix files."""
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
# PARSING
# =============================================================================

def parse_matrix_cell(cell_value):
    """Parse matrix cell. Returns (should_use, notes)."""
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
    """Parse CSV matrix into {req_num: {"objections": [...], "notes": "..."}}."""
    result = {}
    
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
                objection_cols.append(col)
        
        if not request_col:
            return result
        
        for row in reader:
            req_num = (row.get(request_col) or "").strip()
            if not req_num:
                continue
            
            objections = []
            for col in objection_cols:
                cell_val = row.get(col, "")
                should_use, cell_notes = parse_matrix_cell(cell_val)
                if should_use:
                    objections.append({"name": col, "notes": cell_notes})
            
            notes_val = (row.get(notes_col) or "").strip() if notes_col else ""
            result[req_num] = {"objections": objections, "notes": notes_val}
    
    return result

def parse_discovery_file(filepath):
    """Parse discovery requests from file."""
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

# =============================================================================
# STATE MANAGEMENT
# =============================================================================

def new_state():
    """Create empty state."""
    return {
        "schema_version": "3.1",
        "created": now_iso(),
        "last_updated": now_iso(),
        "baselines": {
            "files": {},  # {filepath: {"hash": ..., "captured_at": ...}}
        },
        "pairs": {},  # {pair_id: {"discovery": ..., "matrix": ..., "requests": {...}}}
        "history": []
    }

def load_state():
    """Load state from file."""
    if not STATE_FILE.exists():
        return new_state()
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except:
        return new_state()

def save_state(state):
    """Save state to file."""
    state["last_updated"] = now_iso()
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

def get_pair_id(disc_path, matrix_path):
    """Generate unique ID for a discovery/matrix pair."""
    return f"{disc_path.stem}|{matrix_path.stem}"

# =============================================================================
# COMMANDS
# =============================================================================

def cmd_init():
    """Initialize/reset baseline from current files."""
    state = new_state()
    ts = now_iso()
    pairs = auto_match_pairs()
    
    print(f"Initializing baseline...")
    print(f"Found {len(pairs)} discovery/matrix pair(s)")
    print()
    
    # Capture file baselines
    for path in [OBJECTION_LANG_FILE, CASE_SUMMARY_FILE]:
        if path.exists():
            state["baselines"]["files"][str(path.name)] = {
                "hash": file_hash(path),
                "captured_at": ts
            }
    
    # Process each pair
    for disc_path, matrix_path in pairs:
        pair_id = get_pair_id(disc_path, matrix_path)
        dtype = detect_discovery_type(disc_path.name)
        
        print(f"  [{dtype}] {disc_path.name} + {matrix_path.name}")
        
        # Capture file hashes
        state["baselines"]["files"][disc_path.name] = {"hash": file_hash(disc_path), "captured_at": ts}
        state["baselines"]["files"][matrix_path.name] = {"hash": file_hash(matrix_path), "captured_at": ts}
        
        # Parse current state
        matrix_data = parse_matrix(matrix_path)
        
        state["pairs"][pair_id] = {
            "discovery": disc_path.name,
            "matrix": matrix_path.name,
            "type": dtype,
            "requests": {}
        }
        
        for req_num, data in matrix_data.items():
            obj_names = [o["name"] for o in data["objections"]]
            state["pairs"][pair_id]["requests"][req_num] = {
                "objections": obj_names,
                "notes": data["notes"],
                "captured_at": ts
            }
        
        print(f"    {len(matrix_data)} requests captured")
    
    # Record in history
    state["history"].append({
        "action": "init",
        "timestamp": ts,
        "pairs_count": len(pairs),
        "pair_ids": list(state["pairs"].keys())
    })
    
    save_state(state)
    print()
    print(f"[OK] Baseline saved to {STATE_FILE.name}")

def cmd_check():
    """Show what changed since baseline."""
    state = load_state()
    
    if not state["pairs"]:
        print("No baseline found. Run --init first.")
        return
    
    print("=" * 60)
    print("CHANGE CHECK")
    print("=" * 60)
    print()
    
    # Check file changes
    file_changes = []
    for filename, baseline in state["baselines"]["files"].items():
        path = BASE_DIR / filename
        current_hash = file_hash(path)
        if current_hash != baseline["hash"]:
            file_changes.append((filename, baseline["hash"], current_hash))
    
    if file_changes:
        print("FILE CHANGES:")
        for fname, old_h, new_h in file_changes:
            print(f"  * {fname}")
            print(f"    Baseline: {old_h or 'N/A'}")
            print(f"    Current:  {new_h or 'DELETED'}")
        print()
    
    # Check request changes
    all_changes = []
    for pair_id, pair_data in state["pairs"].items():
        matrix_path = BASE_DIR / pair_data["matrix"]
        if not matrix_path.exists():
            print(f"  [!] Matrix file missing: {pair_data['matrix']}")
            continue
        
        current_matrix = parse_matrix(matrix_path)
        stored_requests = pair_data["requests"]
        
        for req_num, current_data in current_matrix.items():
            current_objs = set(o["name"] for o in current_data["objections"])
            stored_objs = set(stored_requests.get(req_num, {}).get("objections", []))
            
            added = current_objs - stored_objs
            removed = stored_objs - current_objs
            
            if added or removed:
                all_changes.append({
                    "pair_id": pair_id,
                    "type": pair_data["type"],
                    "request": req_num,
                    "added": list(added),
                    "removed": list(removed),
                    "current": list(current_objs)
                })
    
    if all_changes:
        print(f"REQUEST CHANGES ({len(all_changes)}):")
        for c in all_changes:
            action = "REWRITE" if c["removed"] else "AUGMENT"
            print(f"  {c['type']} No. {c['request']}: {action}")
            if c["added"]:
                print(f"    + {', '.join(c['added'])}")
            if c["removed"]:
                print(f"    - {', '.join(c['removed'])}")
        print()
        print("Run --diff to generate edits package.")
    else:
        print("No request changes detected.")
    
    if not file_changes and not all_changes:
        print("[OK] Everything in sync with baseline.")

def cmd_diff():
    """Generate edits prompt package."""
    state = load_state()
    
    if not state["pairs"]:
        print("No baseline found. Run --init first.")
        return
    
    ts = now_iso()
    all_changes = []
    
    # Detect changes
    for pair_id, pair_data in state["pairs"].items():
        disc_path = BASE_DIR / pair_data["discovery"]
        matrix_path = BASE_DIR / pair_data["matrix"]
        
        if not matrix_path.exists():
            continue
        
        disc_texts = parse_discovery_file(disc_path) if disc_path.exists() else {}
        current_matrix = parse_matrix(matrix_path)
        stored_requests = pair_data["requests"]
        
        for req_num, current_data in current_matrix.items():
            current_objs = [o["name"] for o in current_data["objections"]]
            current_obj_set = set(current_objs)
            stored_objs = set(stored_requests.get(req_num, {}).get("objections", []))
            
            added = current_obj_set - stored_objs
            removed = stored_objs - current_obj_set
            
            if added or removed:
                all_changes.append({
                    "type": pair_data["type"],
                    "request": req_num,
                    "request_text": disc_texts.get(req_num, "[TEXT NOT FOUND]"),
                    "added": list(added),
                    "removed": list(removed),
                    "current": current_objs,
                    "notes": current_data["notes"],
                    "action": "REWRITE" if removed else "AUGMENT"
                })
    
    # Generate package
    lines = []
    lines.append("# DISCOVERY OBJECTIONS - EDITS PACKAGE")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Working Directory:** `{BASE_DIR}`")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # Instructions
    lines.append("## INSTRUCTIONS")
    lines.append("")
    lines.append("Draft revised objection prose for each changed request below.")
    lines.append("")
    lines.append("- **AUGMENT:** Add new objection grounds to existing prose")
    lines.append("- **REWRITE:** Start fresh with only currently marked objections")
    lines.append("")
    lines.append("Use the approved templates in `objection_language.txt` as your foundation.")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # Changes
    if not all_changes:
        lines.append("## NO CHANGES")
        lines.append("")
        lines.append("Everything is in sync.")
    else:
        lines.append(f"## CHANGES ({len(all_changes)})")
        lines.append("")
        
        for c in all_changes:
            lines.append(f"### {c['type']} NO. {c['request']} — {c['action']}")
            lines.append("")
            lines.append("**TEXT:**")
            lines.append(f"> {c['request_text'][:500]}")
            lines.append("")
            if c["added"]:
                lines.append(f"**ADDED:** {', '.join(c['added'])}")
            if c["removed"]:
                lines.append(f"**REMOVED:** {', '.join(c['removed'])}")
            lines.append(f"**CURRENT:** {', '.join(c['current']) if c['current'] else 'None'}")
            lines.append("")
            if c["notes"]:
                lines.append(f"**NOTES:** {c['notes']}")
                lines.append("")
            lines.append("**REVISED PROSE:**")
            lines.append("```")
            lines.append("[DRAFT HERE]")
            lines.append("```")
            lines.append("")
            lines.append("---")
            lines.append("")
    
    EDITS_PACKAGE.write_text("\n".join(lines), encoding="utf-8")
    
    # Record in history
    state["history"].append({
        "action": "diff",
        "timestamp": ts,
        "changes_count": len(all_changes)
    })
    save_state(state)
    
    print(f"[OK] Generated {EDITS_PACKAGE.name}")
    print(f"  {len(all_changes)} request(s) need attention")

def cmd_apply(file_path=None):
    """Apply completed edits."""
    path = Path(file_path) if file_path else EDITS_PACKAGE
    if not path.exists():
        print(f"File not found: {path}")
        return
    
    content = path.read_text(encoding="utf-8")
    state = load_state()
    ts = now_iso()
    
    # Parse completed edits
    pattern = r'### (\w+) NO\. ([\d.]+) [—–-] (AUGMENT|REWRITE).*?\*\*REVISED PROSE:\*\*\s*```\s*(.*?)\s*```'
    matches = re.findall(pattern, content, re.DOTALL)
    
    applied = []
    for dtype, req_num, action, prose in matches:
        prose = prose.strip()
        if prose == "[DRAFT HERE]" or not prose:
            continue
        
        applied.append({
            "type": dtype,
            "request": req_num,
            "action": action,
            "prose": prose
        })
        print(f"  [OK] {dtype} No. {req_num}: {action}")
    
    if applied:
        state["history"].append({
            "action": "apply",
            "timestamp": ts,
            "applied_count": len(applied),
            "edits": [{"type": a["type"], "request": a["request"]} for a in applied]
        })
        save_state(state)
    
    print()
    print(f"[OK] Applied {len(applied)} edit(s)")
    print("Note: This records the edits in history. Update your final .md files manually.")

def cmd_snapshot(note=""):
    """Take a snapshot of current state."""
    state = load_state()
    ts = now_iso()
    
    # Capture current hashes
    current_hashes = {}
    for f in list(BASE_DIR.glob("*.txt")) + list(BASE_DIR.glob("*.csv")) + list(BASE_DIR.glob("*.md")):
        current_hashes[f.name] = file_hash(f)
    
    state["history"].append({
        "action": "snapshot",
        "timestamp": ts,
        "note": note,
        "file_count": len(current_hashes)
    })
    save_state(state)
    
    print(f"[OK] Snapshot recorded")
    if note:
        print(f"  Note: {note}")
    print(f"  Files: {len(current_hashes)}")

def cmd_status():
    """Show baseline status."""
    state = load_state()
    
    print("=" * 60)
    print("BASELINE STATUS")
    print("=" * 60)
    print()
    
    if not state["pairs"]:
        print("No baseline found. Run --init first.")
        return
    
    print(f"Schema: {state.get('schema_version', 'unknown')}")
    print(f"Created: {state.get('created', 'unknown')}")
    print(f"Last Updated: {state.get('last_updated', 'unknown')}")
    print()
    
    print("PAIRS:")
    for pair_id, pair_data in state["pairs"].items():
        req_count = len(pair_data.get("requests", {}))
        print(f"  [{pair_data['type']}] {pair_data['discovery']} + {pair_data['matrix']}")
        print(f"       {req_count} requests")
    print()
    
    print(f"History entries: {len(state.get('history', []))}")

def cmd_history():
    """Show audit history."""
    state = load_state()
    
    print("=" * 60)
    print("AUDIT HISTORY")
    print("=" * 60)
    print()
    
    history = state.get("history", [])
    if not history:
        print("No history.")
        return
    
    for i, entry in enumerate(history[-20:], 1):  # Show last 20
        print(f"[{i}] {entry['timestamp'][:19]}")
        print(f"    Action: {entry['action']}")
        
        if entry["action"] == "init":
            print(f"    Pairs: {entry.get('pairs_count', 0)}")
        elif entry["action"] == "diff":
            print(f"    Changes: {entry.get('changes_count', 0)}")
        elif entry["action"] == "apply":
            print(f"    Applied: {entry.get('applied_count', 0)}")
        elif entry["action"] == "snapshot":
            if entry.get("note"):
                print(f"    Note: {entry['note']}")
        print()

# =============================================================================
# MAIN
# =============================================================================

def main():
    args = sys.argv[1:]
    
    print("=" * 60)
    print("DISCOVERY OBJECTIONS - SMART SYNC v3.1")
    print("=" * 60)
    print(f"Working: {BASE_DIR}")
    print()
    
    if "--init" in args:
        cmd_init()
    elif "--check" in args:
        cmd_check()
    elif "--diff" in args:
        cmd_diff()
    elif "--apply" in args:
        idx = args.index("--apply")
        file_arg = args[idx + 1] if idx + 1 < len(args) and not args[idx + 1].startswith("--") else None
        cmd_apply(file_arg)
    elif "--snapshot" in args:
        idx = args.index("--snapshot")
        note = args[idx + 1] if idx + 1 < len(args) and not args[idx + 1].startswith("--") else ""
        cmd_snapshot(note)
    elif "--status" in args:
        cmd_status()
    elif "--history" in args:
        cmd_history()
    else:
        print("Commands:")
        print("  --init              Initialize baseline from current files")
        print("  --check             Show changes since baseline")
        print("  --diff              Generate edits prompt package")
        print("  --apply [FILE]      Record applied edits")
        print("  --snapshot [NOTE]   Record current state")
        print("  --status            Show baseline info")
        print("  --history           Show audit history")
        print()
        print("Workflow:")
        print("  1. Set up your discovery .txt and matrix .csv files")
        print("  2. python smart_sync.py --init")
        print("  3. Edit the matrix CSV")
        print("  4. python smart_sync.py --check")
        print("  5. python smart_sync.py --diff")
        print("  6. Give edits package to AI, get revised prose")
        print("  7. python smart_sync.py --apply")

if __name__ == "__main__":
    main()
