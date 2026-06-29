"""
Rule Filter — 1 LLM call.
Given all extracted rules + dataset column map,
returns only the rules that can actually be verified using this dataset.
"""

from __future__ import annotations

import json

from audit.llm.client import chat
from audit.schemas.rule_schema import DraftRule

_SYSTEM = """\
You are an audit analyst. Given a list of rules and the columns available in a dataset,
identify which rules can be verified using this dataset.

A rule is APPLICABLE if the dataset has columns that contain evidence to check it.
  Example: "Attribution within 30 days" → dataset has date columns → APPLICABLE

A rule is NOT APPLICABLE if the dataset simply has no columns for that rule.
  Example: "Procedure approved by MQ dept" → dataset has no approval column → NOT APPLICABLE

Return ONLY valid JSON:
{
  "applicable": ["PROC2_R01", "PROC2_R03"],
  "not_applicable": ["PROC2_R02"],
  "reasoning": {
    "PROC2_R02": "no approval or sign-off column found in dataset"
  }
}"""


def filter_rules(
    rules: list[DraftRule],
    col_map: dict[str, dict],
) -> tuple[list[DraftRule], dict[str, str]]:
    """
    Single LLM call.
    Returns (applicable_rules, {dropped_rule_id: reason}).
    """
    rules_text = "\n".join(
        f"[{r.rule_id}] {r.rule_type} | {r.statement} | keywords: {', '.join(r.keywords)}"
        for r in rules
    )
    cols_text = "\n".join(
        f"  {h}: {info.get('meaning', '')} ({info.get('semantic_role', '')})"
        for h, info in col_map.items()
        if info.get("audit_relevant")
    )

    response = chat(
        [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": (
                f"Rules to evaluate:\n{rules_text}\n\n"
                f"Dataset columns available:\n{cols_text}"
            )},
        ],
        json_mode=True,
    )

    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        return rules, {}

    applicable_ids = set(data.get("applicable", [r.rule_id for r in rules]))
    reasoning      = data.get("reasoning", {})

    applicable = [r for r in rules if r.rule_id in applicable_ids]
    dropped    = {
        r.rule_id: reasoning.get(r.rule_id, "not verifiable from this dataset")
        for r in rules if r.rule_id not in applicable_ids
    }

    return applicable, dropped
