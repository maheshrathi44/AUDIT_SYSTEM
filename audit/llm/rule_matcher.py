"""
LLM rule matcher — for each dataset row, finds which extracted rules are relevant.
No hardcoded column names, no domain-specific logic. Works for any dataset + any procedures.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from audit.llm.client import chat
from audit.schemas.rule_schema import DraftRule

_PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

_SYSTEM = """\
You are an audit rule relevance analyst.

Given:
1. A data row with field values
2. A list of rules extracted from procedure documents

Identify which rules are RELEVANT to this specific row.

A rule is relevant if:
- The row's status, category, or values make this rule applicable to this case
- The rule defines a timeline that can be checked against dates in this row
- The rule's topic matches the subject/content of this row
- The row's outcome (closed, superseded, rejected, etc.) triggers this rule

Return ONLY valid JSON:
{
  "relevant_rules": [
    {
      "rule_id": "PROC01_R03",
      "relevance": "one sentence explaining exactly why this rule applies to this row",
      "priority": "critical|high|medium|low"
    }
  ]
}

Priority guide:
  critical — timeline breach possible, or mandatory step clearly violated
  high     — strong match, likely applicable
  medium   — possibly applicable, needs audit check
  low      — tangentially related

Only include rules that genuinely apply. Skip rules that clearly don't relate to this row.
Order by priority (critical first)."""


def match_rules_for_row(
    row: dict[str, str],
    rules: list[DraftRule],
    column_map: dict[str, dict],
) -> list["RelevantRule"]:
    """
    Ask LLM which rules from `rules` apply to this `row`.
    Returns list of RelevantRule sorted by priority (critical first).
    """
    # Only pass audit-relevant columns to LLM (reduces tokens)
    audit_row = {
        k: v for k, v in row.items()
        if v and column_map.get(k, {}).get("audit_relevant", True)
    }
    row_text = "\n".join(f"  {k}: {v}" for k, v in audit_row.items())

    # Build compact rules summary
    rules_text = ""
    for r in rules:
        tl = f" [timeline: {r.timeline_days} days]" if r.timeline_days else ""
        rules_text += (
            f"[{r.rule_id}] type={r.rule_type}, priority={r.priority}{tl}\n"
            f"  Statement: {r.statement}\n"
            f"  Keywords: {', '.join(r.keywords)}\n\n"
        )

    response = chat(
        [
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Data row:\n{row_text}\n\n"
                    f"Rules to evaluate:\n{rules_text}"
                ),
            },
        ],
        json_mode=True,
    )

    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        print("  WARN: rule matcher returned invalid JSON for this row")
        return []

    rule_index = {r.rule_id: r for r in rules}
    matched: list[RelevantRule] = []

    for item in data.get("relevant_rules", []):
        rid  = item.get("rule_id", "")
        rule = rule_index.get(rid)
        if rule:
            matched.append(RelevantRule(
                rule=rule,
                relevance=item.get("relevance", ""),
                priority=item.get("priority", "medium"),
            ))

    matched.sort(key=lambda m: _PRIORITY_ORDER.get(m.priority, 3))
    return matched


@dataclass
class RelevantRule:
    rule: DraftRule
    relevance: str    # why this rule applies to this specific row
    priority: str     # critical / high / medium / low
