"""
Rule Check Generator — translates each applicable rule into a computation spec (RuleCheck).
Batched LLM calls (~4 calls for 30 rules). No caching.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from audit.llm.client import chat, get_model
from audit.schemas.rule_schema import DraftRule

_SYSTEM = """\
You are an audit analyst. For each rule, create a RuleCheck — a precise computation spec
for how to verify that rule against a dataset.

=== COLUMN MATCHING GUIDE ===

Each column below has: name, semantic_role, meaning, data_type.
Use semantic_role to identify the RIGHT column for each rule concept.

TIMELINE RULES ("within X days", "must happen within X days of Y"):
  → check_type: "formula", computation: "date_difference"
  → column_a: the START/ORIGIN date  (role: date_reported, date_raised, date_opened)
  → column_b: the END/EVENT date     (role: date_closed, date_received, date_replied, date_approved)
  → threshold: X (integer — number of days)
  → pass_condition: "<=" (within threshold) or ">=" (at least threshold)
  → CRITICAL: both columns must be actual column names from the dataset.
    If you cannot confidently identify BOTH dates, use "judgment" instead.

CONDITIONAL TIMELINE RULES ("if [condition] then check within X days"):
  → Same as TIMELINE RULES but also set:
  → filter_column: exact name of the column whose value triggers the check
  → filter_value: the value that must be present for the rule to apply (e.g. "No", "Yes", "Open")
  → Rows where filter_column != filter_value are skipped (treated as missing → still count as compliant)
  Example: "close if no part received within 30 days" → filter_column: "Parts Availability", filter_value: "No"

MANDATORY FIELD RULES ("must be filled", "shall be raised", "is required", "must be present"):
  → check_type: "formula", computation: "not_blank"
  → column_a: the field that must not be empty   (role: identifier, status, date_*, etc.)
  → threshold: null, column_b: null

STATUS / VALUE RULES ("must be in state X", "should show Y", "must contain Z"):
  → check_type: "formula", computation: "value_contains"
  → column_a: the status or text column
  → pass_condition: the exact keyword/value the rule expects (read it directly from the rule statement)

DOCUMENT PRESENCE RULES ("form X must be attached", "certificate must be provided"):
  → If a supported document is listed: check_type: "formula", computation: "value_contains"
  →   column_a: the column storing document references (role: document_ref or identifier)
  →   pass_condition: the document filename exactly as listed
  → Otherwise: check_type: "judgment", sample the document reference column

JUDGMENT (only when no formula is reliably possible):
  → check_type: "judgment"
  → sample_columns: list the most relevant columns that contain evidence for this rule
  → judgment_question: a precise yes/no question answerable from sample rows

=== CRITICAL RULES ===
1. column_a and column_b MUST be exact column names — copy character-for-character from the dataset.
2. A formula check with WRONG column names causes ALL rows to show as "missing".
   Use "judgment" if you are not confident about column identification.
3. threshold is an integer (days) for date_difference; null for everything else.
4. Never use a text column for date_difference — column_a and column_b must both be date columns.
5. If a rule requires checking two separate conditions, create the more important one.

Return ONLY valid JSON — column names in the output must be real column names from the dataset:
{
  "checks": [
    {
      "rule_id": "R01",
      "check_type": "formula",
      "description": "record must be completed within 30 days of being opened",
      "filter_column": "",
      "filter_value": "",
      "column_a": "<exact name of the start/opened date column>",
      "column_b": "<exact name of the end/completed date column>",
      "computation": "date_difference",
      "threshold": 30,
      "pass_condition": "<=",
      "sample_columns": [],
      "judgment_question": ""
    },
    {
      "rule_id": "R02",
      "check_type": "formula",
      "description": "close within 30 days only when part is not available",
      "filter_column": "<exact name of the availability/status column>",
      "filter_value": "No",
      "column_a": "<exact name of the report/open date column>",
      "column_b": "<exact name of the closed/reply date column>",
      "computation": "date_difference",
      "threshold": 30,
      "pass_condition": "<=",
      "sample_columns": [],
      "judgment_question": ""
    },
    {
      "rule_id": "R03",
      "check_type": "formula",
      "description": "reference number must be filled (mandatory field)",
      "column_a": "<exact name of the reference/ID column>",
      "column_b": null,
      "computation": "not_blank",
      "threshold": null,
      "pass_condition": "not_blank",
      "sample_columns": [],
      "judgment_question": ""
    },
    {
      "rule_id": "R07",
      "check_type": "judgment",
      "description": "requires reading free-text content to verify",
      "column_a": null,
      "column_b": null,
      "computation": null,
      "threshold": null,
      "pass_condition": null,
      "sample_columns": ["<most relevant column>", "<second relevant column>"],
      "judgment_question": "<precise yes/no question based on the rule statement>"
    }
  ]
}"""


@dataclass
class RuleCheck:
    rule_id:     str
    rule:        DraftRule
    check_type:  str          # "formula" or "judgment"
    description: str = ""

    # conditional filter — rows that don't match are treated as missing (excluded from compliance)
    # Single-condition (LLM-generated or legacy):
    filter_column: str = ""
    filter_value:  str = ""
    # Multi-condition (user-set in page 4 UI — AND logic):
    filter_conditions: list[dict] = field(default_factory=list)  # [{"column": ..., "value": ...}]

    # formula fields
    column_a:      str        = ""
    column_b:      str        = ""
    computation:   str        = ""
    threshold:     int | None = None
    pass_condition: str       = ""

    # judgment fields
    sample_columns:    list[str] = field(default_factory=list)
    judgment_question: str       = ""


def generate_rule_checks(
    rules: list[DraftRule],
    col_map: dict[str, dict],
    supported_doc_names=None,
    batch_size: int = 8,
) -> list[RuleCheck]:
    """Generate a RuleCheck per rule. Batched LLM calls. No caching."""
    rule_index = {r.rule_id: r for r in rules}
    doc_names  = sorted(supported_doc_names or [])

    cols_text = "\n".join(
        f'  "{h}" — role: {info.get("semantic_role", "?")} | '
        f'meaning: {info.get("meaning", "")} | type: {info.get("data_type", "")}'
        for h, info in col_map.items()
        if info.get("audit_relevant")
    )

    docs_text = ""
    if doc_names:
        docs_text = (
            "\n\nSupported documents (verified by filename match in dataset):\n"
            + "\n".join(f"  {n}" for n in doc_names)
            + "\nFor document-presence rules, use value_contains with the filename as pass_condition."
        )

    all_dicts: list[dict] = []
    for i in range(0, len(rules), batch_size):
        batch = rules[i: i + batch_size]
        rules_text = "\n".join(
            f"[{r.rule_id}] {r.rule_type} — {r.statement}"
            for r in batch
        )
        response = chat(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": (
                    f"Dataset columns (use semantic_role to match columns to rule concepts):\n"
                    f"{cols_text}"
                    f"{docs_text}\n\n"
                    f"Rules — create one RuleCheck per rule:\n{rules_text}"
                )},
            ],
            json_mode=True,
        )
        try:
            all_dicts.extend(json.loads(response).get("checks", []))
        except json.JSONDecodeError:
            print(f"  WARN: batch {i // batch_size + 1} returned invalid JSON")

    print(f"    ({len(all_dicts)} rule checks generated)")
    return [
        dict_to_check(c, rule_index[c["rule_id"]])
        for c in all_dicts
        if c.get("rule_id") in rule_index
    ]


def dict_to_check(c: dict, rule: DraftRule) -> RuleCheck:
    """Public — also used to rebuild a RuleCheck from a saved Past Observations entry."""
    return RuleCheck(
        rule_id=c.get("rule_id", ""),
        rule=rule,
        check_type=c.get("check_type", "judgment"),
        description=c.get("description", ""),
        filter_column=c.get("filter_column") or "",
        filter_value=c.get("filter_value") or "",
        filter_conditions=c.get("filter_conditions") or [],
        column_a=c.get("column_a") or "",
        column_b=c.get("column_b") or "",
        computation=c.get("computation") or "",
        threshold=c.get("threshold"),
        pass_condition=c.get("pass_condition") or "",
        sample_columns=c.get("sample_columns") or [],
        judgment_question=c.get("judgment_question") or "",
    )
