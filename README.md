# AI Compliance Audit Engine

An AI-powered tool that reads a **procedure document** (and optionally a **past audit report**), figures out every rule that can be checked against your data, then runs those checks against a full **Excel dataset** — and gives you a rule-by-rule verdict (Pass / Partial / Fail / Missing) with evidence, risk level, and a downloadable report.

Built for MSIL QA-QD FTIR-style audits, but works with any procedure + spreadsheet pair.

---

## 1. What it actually does (in plain language)

You upload three things:
1. **Procedure document(s)** (PDF / DOCX / TXT) — the rulebook. "Reply must be sent within 30 days", "must be approved by manager", etc.
2. **Past audit report(s)** (optional) — a previous human-written audit. The AI reads its findings and turns them into extra rules, and trusts these more (see Confidence below) since a human already validated them.
3. **Dataset(s)** (Excel) — the actual records you want audited.

The system then walks you through **5 pages**, pausing for your review at each step so nothing runs blind:

| Page | What happens |
|---|---|
| **1. Upload** | Upload procedures, optional past report(s) + page range, and your dataset(s). |
| **2. Column Mapping** | AI reads your dataset's columns and guesses what each one means (a date? a status? an ID?). You confirm or fix it. |
| **3. Rule Review** | AI extracts every checkable rule from the procedure/report and tells you which ones apply to *this* dataset. You can edit, restore dropped rules, or add your own. |
| **4. Rule Check Review** | For every rule, AI decides *how* to check it — a **Formula check** (exact, zero-AI, e.g. "date B − date A ≤ 30") or a **Judgment check** (AI reads free text and decides pass/fail). You review and correct these before anything runs. |
| **5. Results** | Every row gets evaluated. You get a verdict card per rule — Pass/Partial/Fail/Missing, risk level, confidence, and real example rows — plus a downloadable report and a **Past Audit Settings** file to speed up your next run. |

---

## 2. Key features, explained

### Formula checks vs. Judgment checks
- **Formula check** — pure Python, zero AI calls per row. Used when a column value directly answers the rule (e.g. two date columns, a "not blank" field, a status value). Fast, deterministic, 100% coverage.
- **Judgment check** — AI reads the relevant column(s) for every row and classifies it pass / fail / indeterminate — also 100% coverage, just AI-driven instead of formula-driven. Used when the rule needs reading free text (e.g. "was the fix a genuine root-cause countermeasure?").

### Conditional filters
Any rule can be scoped with a filter — e.g. "only check rows where Status = Closed". Rows that don't match the filter are marked **Missing**, not penalized, and excluded from the compliance percentage.

### Confidence (Low / Medium / High)
Separate from the Pass/Fail verdict — tells you how much to trust the *rule itself*, based on your own Confirm/Disagree clicks:
- Rules pulled from a **past audit report** start at **High** (a human already validated this finding).
- Rules pulled from the **procedure** start at **Medium** (neutral, no votes yet).
- Clicking **Confirm** a few times in a row pushes it to High; **Disagree** pushes it to Low. Clicking the same button again undoes it.
- This tally is saved and carried forward automatically (see below).

### Past Audit Settings (.json)
After a run, download this file. On your **next** audit of the same procedure/dataset, upload it back on Page 1 and the system pre-fills:
- your confirmed column mappings
- which rules were applicable/dropped (and why)
- your edited check configurations (filters, thresholds, computations)
- your confidence tally (confirm/disagree counts)

This means you only review *new* things each time, not the whole audit from scratch. (Matched by rule ID — if the procedure changes enough that the AI assigns new rule IDs, those specific rules fall back to a fresh review.)

### OCR for scanned PDFs
If a procedure or past audit report PDF has no extractable text (i.e. it's a scan/photo), the system automatically falls back to OCR (Tesseract) to read it. You can also select specific page ranges to extract from (e.g. `1, 3, 5-7`) instead of the whole document.

### Multiple datasets, one run
You can queue several Excel datasets against the same procedure(s) in one session — each gets its own report, and column-mapping/rule decisions are reused across datasets that share the same column layout.

---

## 3. How to run it

### Step 1 — Install Python dependencies
```bash
pip install -r requirements.txt
```

### Step 2 — Install OCR tools (only needed if your procedure/report PDFs are scanned images)
- **Tesseract OCR** — reads text out of images
- **Poppler** — converts PDF pages to images for Tesseract to read

macOS:
```bash
brew install tesseract poppler
```
Windows: download and install both, then note their install paths (you'll need them in Step 3 if they're not on your system PATH).

### Step 3 — Configure `.env`
Create a `.env` file in the project root (copy the format below) with your LLM provider details:

```env
AUDIT_API_KEY=your_api_key_here
AUDIT_BASE_URL=https://api.groq.com/openai/v1
AUDIT_MODEL=llama-3.3-70b-versatile

# Only needed if OCR tools aren't on your system PATH (common on Windows):
# POPPLER_PATH=C:\poppler\Library\bin
# TESSERACT_PATH=C:\Program Files\Tesseract-OCR\tesseract.exe

# Only needed on a corporate network behind a proxy:
# HTTPS_PROXY=http://your-proxy-server:port
# AUDIT_SSL_VERIFY=0
```

The system works with **any OpenAI-compatible API** — swap `AUDIT_BASE_URL` and `AUDIT_MODEL` to switch providers:

| Provider | `AUDIT_BASE_URL` | Example `AUDIT_MODEL` |
|---|---|---|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Groq | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-2.0-flash` |
| Databricks | `https://<workspace>/serving-endpoints` | `databricks-gemini-2-5-flash` |

### Step 4 — Run the app
```bash
streamlit run app.py
```
This opens the app in your browser (usually `http://localhost:8501`). Upload your files and follow the 5 pages.

---

## 4. Project structure

```
app.py                          Streamlit frontend — all 5 pages, UI state
audit/
  pipeline_v2.py                Orchestrates the whole audit (all phases)
  confidence.py                 Confirm/Disagree → Low/Medium/High scoring
  past_observations.py          Build & parse the Past Audit Settings .json
  extractors/
    procedure_reader.py         Reads PDF/DOCX/TXT procedures (+ OCR fallback)
    dataset_reader.py           Reads Excel datasets into plain rows
  llm/
    client.py                   Talks to the LLM API (provider-agnostic)
    rule_extractor.py           Extracts rules from a procedure document
    manual_report_extractor.py  Extracts rules from a past audit report
    column_mapper.py            Guesses semantic meaning of dataset columns
    rule_filter.py               Decides which rules apply to a dataset
    rule_check_generator.py     Turns each rule into a Formula/Judgment check spec
    report_writer.py            Writes the final executive summary
  engine/
    traversal.py                Runs every check against every row (zero AI)
    verdict.py                   Turns raw results into Pass/Partial/Fail/Missing
  schemas/                      Data classes for rules & procedures
requirements.txt                Python dependencies
.env                            Your local config (API key, model, OCR paths) — not committed
```

---

## 5. Troubleshooting

- **"OCR dependencies missing"** — install `pdf2image` + `pytesseract` (`pip install -r requirements.txt`) and make sure Tesseract/Poppler are installed (Step 2 above).
- **OCR runs but returns nothing / wrong text** — set `TESSERACT_PATH` and `POPPLER_PATH` in `.env` to their exact install locations.
- **`AUDIT_API_KEY not set` error** — add it to `.env` in the project root.
- **Corporate network / SSL errors calling the LLM** — set `HTTPS_PROXY` and/or `AUDIT_SSL_VERIFY=0` in `.env`.
- **A rule shows all rows as "Missing"** — the check's column mapping is likely wrong; go back to Page 4 (Rule Check Review) and correct the column selection.
