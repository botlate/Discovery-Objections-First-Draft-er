# Discovery Objections First Draft-er

## Objective
Generates first-draft discovery responses by letting an AI assemble objections from your firm's approved templates based on a spreadsheet selection matrix.

---

## Purpose
Discovery objections are formulaic. The same fifteen objections get lodged in the same boilerplate language across hundreds of requests. But drafting them still takes hours—time billed to clients for work that doesn't require legal judgment, just assembly.

The risk of rushing is waiver. Miss an objection you should have lodged, and you may have waived it. Accidentally include one you shouldn't have, and you look sloppy or invite a meet-and-confer.

This system puts the AI in the driver's seat as the drafter. You supply:
- Your firm's approved objection language
- The discovery requests
- A CSV matrix marking which objections apply to which requests

The system synthesizes everything into a prompt package that any agentic AI can use to draft responses. You get a first draft in your firm's voice. Then you spend your time on what matters: tweaking, rewriting, and applying judgment—not copying and pasting boilerplate.

---

## How It Works

### The Matrix Approach
You fill out a spreadsheet. Rows are discovery requests. Columns are objection types. Put an `x` in a cell to mark that objection for that request. Add notes after a semicolon (`x; definition spans 10 years of project history`) to give the AI context for case-specific reasoning.

The script reads your matrix, pulls the approved language for each marked objection, and generates a prompt package with everything the AI needs to draft responses in your firm's format.

### Example Matrix
| Request | Relevance | Overbroad | Vague & Ambiguous | Privacy (RP) | comments |
|---------|-----------|-----------|-------------------|--------------|----------|
| 1.1 | x | | x | | |
| 2.12 | x | x | x; "INCIDENT" undefined | | |
| 4.1 | x | x | | x | insurance info |

### What Gets Generated
A markdown prompt package containing:
- Your firm's preliminary statement and general objections
- Approved objection templates (numbered for reference)
- Each discovery request with its marked objections
- Case summary for context (if provided)
- Instructions for three-layer response format

Give that file to Claude, GPT, or any capable AI. Get back drafted responses.

---

## The GUI

Two tabs:
1. **Generate Prompts** — Select discovery/matrix pairs, set explanation depth, generate prompt packages
2. **Sync & State** — Track changes to your matrix over time, generate edit packages when you modify objections mid-case

The GUI auto-detects discovery files and matrices in the working folder and matches them by name.

---

## Repo Structure

```
discovery-objections-drafter/
├── discovery_gui_v3.pyw          # Main GUI
├── generate_prompt_packages.py   # CLI script
├── smart_sync.py                 # Change tracking
├── Launch GUI v3.bat             # Windows launcher
├── sample inputs/                # Example input files
│   ├── objection_language.txt    # Approved templates
│   ├── preliminary_objections.txt
│   ├── case_summary.txt
│   ├── Form_Rogs.txt             # Discovery requests
│   └── form_rogs_matrix.csv      # Selection matrix
└── example outputs/
    ├── prompt_FROG_Form_Rogs_121529.md   # Generated prompt package
    └── objection_state.json              # Sync state file
```

---

## Pipeline Scripts

| Script | Purpose | Notes |
|--------|---------|-------|
| `discovery_gui_v3.pyw` | Main GUI for prompt generation and sync | Entry point for most users |
| `generate_prompt_packages.py` | CLI script for generating prompts | Can run standalone without GUI |
| `smart_sync.py` | Tracks matrix changes and generates edit packages | For mid-case modifications |
| `Launch GUI v3.bat` | Windows launcher | Double-click to run |

---

## Quick Start

1. Copy the scripts to your case folder (or copy sample inputs to the script folder)
2. Create/edit your input files:
   - `objection_language.txt` — your firm's templates
   - `preliminary_objections.txt` — boilerplate incorporations
   - `[discovery].txt` — the discovery requests
   - `[discovery]_matrix.csv` — mark objections with `x`
3. Run `Launch GUI v3.bat` or `python discovery_gui_v3.pyw`
4. Click **Generate All Prompts**
5. Give the output `.md` file to your AI of choice

---

## Setup

### Requirements
- Python 3.9+
- tkinter (included with Python on Windows)

### Installation
```bash
git clone [repository]
cd discovery-objections-drafter
```

No pip installs required—uses only standard library.

**Important:** The scripts look for input files in the same directory as the script. Either copy the scripts to your case folder, or copy your input files to the script folder.

### File Setup
Create these files in your working folder:

| File | Required | Purpose |
|------|----------|---------|
| `objection_language.txt` | Yes | Your firm's approved objection templates |
| `preliminary_objections.txt` | Yes | Preliminary statement + general objections |
| `[name].txt` | Yes | Discovery requests (one file per set) |
| `[name]_matrix.csv` | Yes | Objection matrix for that discovery set |
| `case_summary.txt` | No | Case context for smarter drafting |

### Basic Usage
```bash
# GUI (recommended)
python discovery_gui_v3.pyw
# or double-click Launch GUI v3.bat

# CLI
python generate_prompt_packages.py              # Auto-scan folder
python generate_prompt_packages.py --list       # Show detected pairs
python generate_prompt_packages.py --temp 3     # High explanation depth
```

---

## Template Files

### objection_language.txt
Your firm's approved boilerplate. Number each template so the AI can reference them:

```
--------------------------------------------------------------------------------
1. RELEVANCE
--------------------------------------------------------------------------------
Responding Party objects to this [interrogatory/request] on the grounds that it 
seeks information that is not relevant to the subject matter of the pending 
action and is not reasonably calculated to lead to the discovery of admissible 
evidence. (Cal. Code Civ. Proc. § 2017.010.)

--------------------------------------------------------------------------------
2. COMPOUND
--------------------------------------------------------------------------------
...
```

### preliminary_objections.txt
The preliminary statement and general objections that get incorporated by reference in every response. Standard stuff—reserving rights, ongoing investigation, no waiver by answering.

### Discovery Files
Any reasonable format works:
- `Form Interrogatory No. 1.1: [text]`
- `REQUEST FOR ADMISSION NO. 1: [text]`
- `INTERROGATORY NO. 1: [text]`

### Matrix CSV
First column must be request numbers. Other columns are objection types. The system recognizes common aliases:

| Your Column Name | Recognized As |
|------------------|---------------|
| `Vague & Ambiguous` | Vague |
| `Overbroad` | Overbroad |
| `Attorney-Client` | Atty-Client |
| `Privacy (RP)` | Privacy-RP |
| `comments` or `notes` | Notes column |

Any non-empty cell marks that objection for use. Add notes after semicolon: `x; specific reason here`

---

## Explanation Depth (Temperature)

Control how much case-specific reasoning the AI adds:

| Level | Name | Behavior |
|-------|------|----------|
| 0 | Minimal | Template language only, no elaboration |
| 1 | Low | Brief reasoning from cell notes (1 sentence) |
| 2 | Medium | Cell notes + Notes column (1-2 sentences) |
| 3 | High | Full case summary integration (2-3 sentences) |

Higher levels require more setup (case summary, detailed notes) but produce more persuasive objections.

---

## Sync & State Tab

When you modify the matrix mid-case—adding objections, removing them—the sync system tracks what changed and generates targeted edit packages. Instead of regenerating everything, it identifies which requests need attention and whether to augment existing prose or rewrite from scratch.

Commands:
- **Init** — Baseline current state
- **Check** — Show what changed since baseline  
- **Diff** — Generate edit package for changed requests
- **Apply** — Record that edits were applied

---

## Output Format

The AI drafts responses in a three-layer format:

```
### FROG NO. 1.1

Responding Party incorporates by reference the Preliminary Statement and General
Objections, above, as if fully set forth herein.

[Specific objections as flowing prose]

Subject to, and without waiving, the Preliminary Statement, General Objections,
and the foregoing objections, Responding Party responds as follows:

[Substantive response]
```

---

## Known Limitations

- **AI still needs review** — This generates first drafts. Attorney review is mandatory.
- **Format parsing** — Unusual discovery formats may need manual cleanup
- **No document assembly** — Outputs markdown, not Word. Copy-paste into your template.

---

## Status: Beta
Functional and in active use. Contributions and bug reports welcome.

---

## License
MIT License with NLJ-500 Exclusion

Copyright (c) 2025 Rye Murphy

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

1. **Attribution.** The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

2. **NLJ-500 Exclusion.** The rights granted in this License do NOT extend to:
   - (a) any law firm listed in the National Law Journal (NLJ) 500 rankings for the year of use or any prior year, or
   - (b) any employee, partner, shareholder, associate, contractor, or agent of such a firm using the Software within the scope of their work or for the benefit of the firm.

   These firms and individuals are prohibited from using, copying, modifying, merging, publishing, distributing, sublicensing, or selling the Software without my permission. Just email if you want to use. This carveout is not intended to prevent big firm lawyers from experimenting or trying out the Software for personal use. If you're going to use it for work billed at $700/hr you can throw a dollar on my hat.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
