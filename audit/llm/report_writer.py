"""
Report writer — 1 LLM call.
Takes all rule verdicts → generates executive audit summary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from audit.engine.verdict import RuleVerdict
from audit.llm.client import chat

_SYSTEM = """\
You are an audit report writer. Given per-rule compliance results, write an executive summary.

Return ONLY valid JSON:
{
  "overall_compliance_pct": 74,
  "overall_risk": "Medium",
  "risk_areas": [
    "Timeline compliance frequently breached",
    "Mandatory reference field missing in many records"
  ],
  "summary": "3-4 sentence executive summary of the overall audit findings"
}

overall_risk:
  High   — any rule with compliance < 50% or critical rule failed
  Medium — compliance between 60-85% overall
  Low    — overall compliance > 85%"""


@dataclass
class AuditReport:
    overall_compliance_pct: float
    overall_risk:           str
    total_rules_audited:    int
    passed_rules:           list[str]
    failed_rules:           list[str]
    partial_rules:          list[str]
    missing_rules:          list[str]
    risk_areas:             list[str]
    summary:                str
    verdicts:               list[RuleVerdict] = field(default_factory=list)


def generate_report(verdicts: list[RuleVerdict]) -> AuditReport:
    """Single LLM call — writes executive summary from all rule verdicts."""
    verdicts_text = "\n".join(
        f"[{v.rule_id}] {v.verdict} — {v.compliance_pct}% — {v.finding}"
        for v in verdicts
    )

    response = chat(
        [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"Rule verdicts:\n{verdicts_text}"},
        ],
        json_mode=True,
    )

    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        data = {}

    return AuditReport(
        overall_compliance_pct=float(data.get("overall_compliance_pct", 0)),
        overall_risk=data.get("overall_risk", "Medium"),
        total_rules_audited=len(verdicts),
        passed_rules= [v.rule_id for v in verdicts if v.verdict == "Pass"],
        failed_rules= [v.rule_id for v in verdicts if v.verdict == "Fail"],
        partial_rules=[v.rule_id for v in verdicts if v.verdict == "Partial"],
        missing_rules=[v.rule_id for v in verdicts if v.verdict == "Missing"],
        risk_areas=data.get("risk_areas", []),
        summary=data.get("summary", ""),
        verdicts=verdicts,
    )
