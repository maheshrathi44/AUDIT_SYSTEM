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
You are an audit report writer. Given per-rule non-compliance results, write an executive summary.

IMPORTANT — always phrase results in terms of NON-COMPLIANCE percentage (the share of
records that VIOLATE a rule), never compliance percentage. Do not write "82% compliant"
or "a compliance rate of 82%" — write "18% non-compliance" or "18% of records were
non-compliant" instead. This applies to both "summary" and "risk_areas".

Return ONLY valid JSON:
{
  "overall_noncompliance_pct": 18,
  "overall_risk": "Medium",
  "risk_areas": [
    "Timeline compliance rule frequently breached — 24% non-compliance",
    "Mandatory reference field missing in many records — 12% non-compliance"
  ],
  "summary": "3-4 sentence executive summary of the overall audit findings, phrased using non-compliance percentages throughout"
}

overall_risk:
  High   — any rule with non-compliance > 50% or a critical rule failed
  Medium — overall non-compliance between 15-40%
  Low    — overall non-compliance under 15%"""


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
        f"[{v.rule_id}] {v.verdict} — {round(100 - v.compliance_pct, 1)}% non-compliance — {v.finding}"
        for v in verdicts
    )

    response = chat(
        [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"Rule verdicts (non-compliance %):\n{verdicts_text}"},
        ],
        json_mode=True,
    )

    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        data = {}

    overall_noncompliance_pct = float(data.get("overall_noncompliance_pct", 0))
    return AuditReport(
        overall_compliance_pct=round(100 - overall_noncompliance_pct, 1),
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
