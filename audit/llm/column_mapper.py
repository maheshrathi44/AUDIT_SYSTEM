"""
LLM column mapper — called once per dataset.
Reads headers + a few sample rows → understands what each column means semantically.
Works for any dataset from any domain.
"""

from __future__ import annotations

import json

from audit.llm.client import chat

_SYSTEM = """\
You are a data analyst. Given column headers and sample rows from a dataset,
describe what each column represents with PRECISE semantic roles.

Return ONLY valid JSON:
{
  "columns": {
    "Column Name": {
      "meaning": "brief description of what this column holds",
      "data_type": "date|text|number|status|id|boolean",
      "semantic_role": "one of the roles listed below",
      "audit_relevant": true
    }
  }
}

semantic_role — choose the MOST SPECIFIC role that applies:

DATE ROLES (be precise — do not use a generic date role):
  date_reported   — when the case/defect/issue was first raised, reported, or opened
  date_closed     — when the case was closed, resolved, finalized, or completed
  date_received   — when a part, item, reply, or response was received
  date_replied    — when a reply, response, or countermeasure was submitted
  date_approved   — when approval, sign-off, or authorization was given
  date_deadline   — target date, due date, or expected completion date
  date_other      — any other date (system timestamp, creation date, modification date)

NON-DATE ROLES:
  case_id         — unique record identifier (ticket no., report no., record ID)
  reopen_indicator — marks that a record was reopened, reactivated, or returned for re-investigation
                     after being closed; look for suffixes, flags, or status values that imply
                     the record went through a second lifecycle (e.g. a separate ID column for
                     reactivated records, a boolean reopen flag, or a status meaning re-opened)
  status          — current state of the record (Open, Closed, Pending, etc.)
  category        — classification, ranking, type, grade, priority (A/B/C, Rank)
  description     — free-text description, remarks, repair contents, findings
  identifier      — reference to another record (reference no., part no., vendor code, form no.)
  document_ref    — column storing an attached document name/path/reference
  numeric         — count, duration, amount, days (a number, not a date)
  other           — anything that does not fit the roles above

audit_relevant:
  true  — dates, statuses, identifiers, categories, descriptions relevant to compliance
  false — system-internal codes, display-only fields, row numbers, blank columns"""


def map_columns(
    headers: list[str],
    sample_rows: list[dict[str, str]],
) -> dict[str, dict]:
    """
    Returns {column_name: {meaning, data_type, semantic_role, audit_relevant}}.
    One LLM call per dataset — result is reused for all rows.
    """
    header_list = "\n".join(f"  - {h}" for h in headers if h)
    samples_str = ""
    for i, row in enumerate(sample_rows, 1):
        row_str = "\n".join(f"    {k}: {v}" for k, v in list(row.items())[:30] if v)
        samples_str += f"  Row {i}:\n{row_str}\n"

    response = chat(
        [
            {
                "role": "system",
                "content": _SYSTEM,
            },
            {
                "role": "user",
                "content": (
                    f"Dataset columns:\n{header_list}\n\n"
                    f"Sample rows:\n{samples_str}"
                ),
            },
        ],
        json_mode=True,
    )

    try:
        return json.loads(response).get("columns", {})
    except json.JSONDecodeError:
        print("  WARN: column mapper returned invalid JSON")
        return {}
