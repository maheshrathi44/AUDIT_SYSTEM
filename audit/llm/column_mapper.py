"""
LLM column mapper — one LLM call per dataset.

Two-stage approach (zero extra LLM calls):
  Stage 1 (zero LLM): statistically profile every column from actual row data —
      unique ratio, null rate, date patterns, cardinality, sample values.
  Stage 2 (one LLM call): pass the statistical profiles + signals to the LLM
      so it has hard evidence, not guesswork, for assigning semantic roles.

This reliably detects primary keys (unique_ratio ≈ 1.0), date columns (pattern match),
status columns (very few distinct values), and numeric columns.
"""

from __future__ import annotations

import json
import re

from audit.llm.client import chat

# ── Statistical analysis (zero LLM) ───────────────────────────────────────────

_DATE_RE = re.compile(
    r'^\s*(\d{1,4}[-/\.]\d{1,2}[-/\.]\d{1,4}'   # YYYY-MM-DD or DD/MM/YYYY
    r'|\d{1,2}\s+\w{3,9}\s+\d{2,4}'              # 15 Jan 2023
    r'|\w{3,9}\s+\d{1,2},?\s+\d{2,4})\s*$'       # Jan 15, 2023
)

_MAX_ANALYSIS_ROWS = 300   # cap for performance on large datasets


def _profile_column(col: str, rows: list[dict]) -> dict:
    """
    Statistical profile of one column from row data.
    Returns signals the LLM uses to assign semantic roles accurately.
    """
    values = [str(r.get(col, "")).strip() for r in rows]
    total  = len(values)
    non_null = [v for v in values if v]
    n = len(non_null)

    if n == 0:
        return {
            "null_ratio": 1.0, "unique_ratio": 0.0, "distinct_count": 0,
            "is_date": False, "is_numeric": False, "is_low_cardinality": False,
            "sample_values": [],
        }

    # Distinct values (preserve insertion order, deduplicate)
    seen: dict[str, None] = {}
    for v in non_null:
        seen[v] = None
    distinct_vals  = list(seen.keys())
    distinct_count = len(distinct_vals)

    # Uniqueness — primary key signal: unique_ratio close to 1.0
    unique_ratio = round(distinct_count / n, 3)
    null_ratio   = round((total - n) / total, 3)

    # Date detection — >70% of non-null values match date patterns
    date_hits = sum(1 for v in non_null if _DATE_RE.match(v))
    is_date   = date_hits / n > 0.70

    # Numeric detection — >80% of non-null values parse as float
    def _is_num(v: str) -> bool:
        try:
            float(v.replace(",", "").replace("%", ""))
            return True
        except ValueError:
            return False

    num_hits   = sum(1 for v in non_null if _is_num(v))
    is_numeric = num_hits / n > 0.80 and not is_date

    # Low-cardinality (status / category / boolean signal)
    is_low_cardinality = distinct_count <= 8 and not is_date and not is_numeric

    # Representative sample values (up to 6 distinct non-null)
    sample_values = distinct_vals[:6]

    return {
        "null_ratio":          null_ratio,
        "unique_ratio":        unique_ratio,
        "distinct_count":      distinct_count,
        "is_date":             is_date,
        "is_numeric":          is_numeric,
        "is_low_cardinality":  is_low_cardinality,
        "sample_values":       sample_values,
    }


def _format_profiles(headers: list[str], rows: list[dict]) -> str:
    """
    Build a per-column statistical summary string for the LLM prompt.
    Much more informative than raw sample rows.
    """
    sample_rows = rows[:_MAX_ANALYSIS_ROWS]
    lines: list[str] = []

    for col in headers:
        if not col:
            continue
        p = _profile_column(col, sample_rows)

        # Build signal tags
        signals: list[str] = []
        if p["unique_ratio"] >= 0.95 and not p["is_date"] and p["distinct_count"] > 5:
            signals.append("HIGH_UNIQUENESS → likely primary key / case ID")
        if p["is_date"]:
            signals.append("IS_DATE → assign a date_* role")
        if p["is_numeric"]:
            signals.append("IS_NUMERIC → numeric or date role")
        if p["is_low_cardinality"]:
            signals.append(f"LOW_CARDINALITY ({p['distinct_count']} distinct) → status / category / boolean")
        if p["null_ratio"] > 0.5:
            signals.append(f"MOSTLY_NULL ({int(p['null_ratio']*100)}%) → low audit relevance")

        sample_str = ", ".join(f'"{v}"' for v in p["sample_values"]) if p["sample_values"] else "(all blank)"

        lines.append(
            f'  "{col}"\n'
            f'    unique_ratio={p["unique_ratio"]}  null_ratio={p["null_ratio"]}  '
            f'distinct_count={p["distinct_count"]}\n'
            f'    sample_values: {sample_str}\n'
            + (f'    SIGNALS: {" | ".join(signals)}\n' if signals else "")
        )

    return "\n".join(lines)


# ── LLM system prompt ──────────────────────────────────────────────────────────

_SYSTEM = """\
You are a data analyst. Given column names with their statistical profiles and sample values,
assign precise semantic roles and meanings to each column.

Return ONLY valid JSON:
{
  "columns": {
    "Column Name": {
      "meaning": "concise description of what this column holds",
      "data_type": "date|text|number|status|id|boolean",
      "semantic_role": "one of the roles listed below",
      "audit_relevant": true
    }
  }
}

semantic_role — choose the MOST SPECIFIC role that applies:

DATE ROLES (only when IS_DATE signal is present or column name implies a date):
  date_reported   — when the case/defect/issue was first raised, reported, or opened
  date_closed     — when the case was closed, resolved, finalized, or completed
  date_received   — when a part, item, reply, or response was received
  date_replied    — when a reply, response, or countermeasure was submitted
  date_approved   — when approval, sign-off, or authorization was given
  date_deadline   — target date, due date, or expected completion date
  date_other      — any other date (system timestamp, creation date)

NON-DATE ROLES:
  case_id         — unique record identifier (use when HIGH_UNIQUENESS signal is present
                    and values look like IDs, codes, or record numbers — NOT plain integers)
  reopen_indicator — marks that a record was reopened or returned for re-investigation;
                    look for a second ID column, reopen flag, or suffix implying re-activation
  status          — current state of the record (Open, Closed, Pending, etc.)
  category        — classification, ranking, type, grade, or priority (A/B/C, Rank, etc.)
  description     — free-text description, remarks, repair contents, findings
  identifier      — reference to another record (part no., vendor code, form no.)
  document_ref    — column storing a document name, path, or reference
  numeric         — count, duration, amount, days (a number with meaning, not an ID)
  other           — anything that does not fit the roles above

HOW TO USE THE SIGNALS:
  HIGH_UNIQUENESS → assign case_id if values look like codes/IDs (not plain row numbers)
  IS_DATE         → assign the most specific date_* role based on the column name
  LOW_CARDINALITY → assign status (if state values) or category (if classification)
  IS_NUMERIC      → assign numeric unless it is clearly a date or identifier
  MOSTLY_NULL     → set audit_relevant: false

audit_relevant:
  true  — dates, statuses, IDs, categories, descriptions that are relevant to compliance checks
  false — row numbers, system-internal codes, display-only fields, mostly-blank columns"""


# ── Public API ─────────────────────────────────────────────────────────────────

def map_columns(
    headers:  list[str],
    all_rows: list[dict[str, str]],
) -> dict[str, dict]:
    """
    Returns {column_name: {meaning, data_type, semantic_role, audit_relevant}}.
    One LLM call per dataset. Statistical profiling done locally before the call.
    """
    profiles_str = _format_profiles(headers, all_rows)

    response = chat(
        [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": (
                f"Analyze these {len(headers)} columns:\n\n{profiles_str}"
            )},
        ],
        json_mode=True,
    )

    try:
        return json.loads(response).get("columns", {})
    except json.JSONDecodeError:
        print("  WARN: column mapper returned invalid JSON")
        return {}
