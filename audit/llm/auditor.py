"""
LLM auditor — step 6 + 7.
Step 6: per matched rule → Pass / Fail / Missing Info + reason
Step 7: row-level summary → overall finding, risk, key issues
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from audit.llm.client import chat
from audit.llm.rule_matcher import RelevantRule

_VERDICT_SYSTEM = """\
You are an auditor. You are given a data row and a list of rules that apply to it.
For each rule, check whether the row PASSES or FAILS the rule, or if data is MISSING to decide.

Return ONLY valid JSON:
{
  "verdicts": [
    {
      "rule_id": "PROC2_R01",
      "verdict": "Pass",
      "reason": "one sentence explaining the verdict using actual values from the row",
      "actual_value": "what the row actually shows for this rule (e.g. '45 days', 'Under Investigation', 'Yes')",
      "expected_value": "what the rule requires (e.g. 'within 30 days', 'must be filed', 'Yes')"
    }
  ]
}

verdict must be exactly one of:
  Pass         — row clearly satisfies the rule
  Fail         — row clearly violates the rule
  Missing Info — data needed to check this rule is absent or blank in the row

Be specific — use actual column values from the row in your reason.
Do not be vague. If dates are present, calculate days and compare against the rule limit."""

_SUMMARY_SYSTEM = """\
You are an audit report writer. Given a data row and its rule verdicts, write a row-level audit finding.

Return ONLY valid JSON:
{
  "overall": "Pass | Fail | Partial",
  "risk": "High | Medium | Low",
  "failed_rules": ["rule_id1", "rule_id2"],
  "missing_rules": ["rule_id3"],
  "summary": "2-3 sentence plain-English summary of what was found for this row — what passed, what failed, what was missing"
}

overall:
  Pass    — all applicable rules satisfied
  Fail    — one or more rules clearly violated
  Partial — some passed, some missing info (no clear violation but incomplete)

risk:
  High   — timeline breached, mandatory step skipped, or critical rule failed
  Medium — partial compliance, missing info on important rules
  Low    — minor gaps or advisory rules only"""


@dataclass
class RuleVerdict:
    rule_id: str
    verdict: str          # Pass / Fail / Missing Info
    reason: str
    actual_value: str
    expected_value: str


@dataclass
class RowFinding:
    overall: str          # Pass / Fail / Partial
    risk: str             # High / Medium / Low
    failed_rules: list[str] = field(default_factory=list)
    missing_rules: list[str] = field(default_factory=list)
    summary: str = ""
    verdicts: list[RuleVerdict] = field(default_factory=list)


def audit_row(
    row: dict[str, str],
    matched: list[RelevantRule],
    column_map: dict[str, dict],
) -> RowFinding:
    """
    Step 6: get Pass/Fail/Missing per rule.
    Step 7: get overall row finding + risk.
    Returns a RowFinding with both.
    """
    if not matched:
        return RowFinding(
            overall="Pass",
            risk="Low",
            summary="No applicable rules found for this row.",
        )

    # Only pass audit-relevant columns to LLM
    audit_row_data = {
        k: v for k, v in row.items()
        if v and column_map.get(k, {}).get("audit_relevant", True)
    }
    row_text = "\n".join(f"  {k}: {v}" for k, v in audit_row_data.items())

    # Build rules block
    rules_text = ""
    for m in matched:
        tl = f" [time limit: {m.rule.timeline_days} days]" if m.rule.timeline_days else ""
        rules_text += (
            f"[{m.rule.rule_id}]{tl}\n"
            f"  Rule: {m.rule.statement}\n"
            f"  Why applicable: {m.relevance}\n\n"
        )

    # ── Step 6: per-rule verdicts ──────────────────────────────────────────
    verdict_response = chat(
        [
            {"role": "system", "content": _VERDICT_SYSTEM},
            {"role": "user", "content": (
                f"Data row:\n{row_text}\n\n"
                f"Rules to audit against:\n{rules_text}"
            )},
        ],
        json_mode=True,
    )

    verdicts: list[RuleVerdict] = []
    try:
        vdata = json.loads(verdict_response)
        for v in vdata.get("verdicts", []):
            verdicts.append(RuleVerdict(
                rule_id=v.get("rule_id", ""),
                verdict=v.get("verdict", "Missing Info"),
                reason=v.get("reason", ""),
                actual_value=v.get("actual_value", ""),
                expected_value=v.get("expected_value", ""),
            ))
    except json.JSONDecodeError:
        pass

    # ── Step 7: row-level summary ──────────────────────────────────────────
    verdicts_text = "\n".join(
        f"  [{v.rule_id}] {v.verdict} — {v.reason}"
        for v in verdicts
    )

    summary_response = chat(
        [
            {"role": "system", "content": _SUMMARY_SYSTEM},
            {"role": "user", "content": (
                f"Data row:\n{row_text}\n\n"
                f"Rule verdicts:\n{verdicts_text}"
            )},
        ],
        json_mode=True,
    )

    overall = "Partial"
    risk = "Medium"
    failed_rules: list[str] = []
    missing_rules: list[str] = []
    summary = ""

    try:
        sdata = json.loads(summary_response)
        overall      = sdata.get("overall", "Partial")
        risk         = sdata.get("risk", "Medium")
        failed_rules = sdata.get("failed_rules", [])
        missing_rules = sdata.get("missing_rules", [])
        summary      = sdata.get("summary", "")
    except json.JSONDecodeError:
        pass

    return RowFinding(
        overall=overall,
        risk=risk,
        failed_rules=failed_rules,
        missing_rules=missing_rules,
        summary=summary,
        verdicts=verdicts,
    )
