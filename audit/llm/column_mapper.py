"""
LLM column mapper — called once per dataset.
Reads headers + one sample row → understands what each column means semantically.
Works for any dataset from any domain.
"""

from __future__ import annotations

import json

from audit.llm.client import chat

_SYSTEM = """\
You are a data analyst. Given column headers from a dataset and one sample row of values,
describe what each column represents.

Return ONLY valid JSON:
{
  "columns": {
    "Column Name": {
      "meaning": "brief description of what this column holds",
      "data_type": "date|text|number|status|id|boolean",
      "semantic_role": "case_id|date_field|status|category|description|numeric|identifier|other",
      "audit_relevant": true
    }
  }
}

semantic_role guide:
  case_id     — unique record identifier (e.g. ticket number, report ID)
  date_field  — any date/timestamp (creation, submission, reply, closure)
  status      — current state of the case/record
  category    — classification, ranking, type, grade
  description — free-text description of the issue or content
  numeric     — count, duration, distance, amount, days
  identifier  — reference to another record (e.g. FPCR number, part number)
  other       — anything that doesn't fit above

audit_relevant = true for anything that matters in a compliance/process audit
  (dates, statuses, IDs, categories, descriptions, timelines).
audit_relevant = false for internal system codes, display-only fields, or blanks."""


def map_columns(
    headers: list[str],
    sample_row: dict[str, str],
) -> dict[str, dict]:
    """
    Returns {column_name: {meaning, data_type, semantic_role, audit_relevant}}.
    One LLM call per dataset — result is reused for all rows.
    """
    header_list = "\n".join(f"  - {h}" for h in headers if h)
    sample_str  = "\n".join(
        f"  {k}: {v}"
        for k, v in list(sample_row.items())[:30]
        if v
    )

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
                    f"Sample row values:\n{sample_str}"
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
