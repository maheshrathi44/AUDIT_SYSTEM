"""
Verdict generator — produces final audit result per rule from DetailedData.
Formula rules: automatic (zero LLM).
Judgment rules: 1 LLM call per rule (small input — just samples).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

from audit.engine.traversal import DetailedData, FormulaResult, JudgmentResult
from audit.llm.client import chat
from audit.llm.rule_check_generator import RuleCheck

_JUDGMENT_SYSTEM = """\
You are an auditor. Given a rule and a sample of data rows, estimate compliance.

Return ONLY valid JSON:
{
  "compliance_pct": 65,
  "verdict": "Partial",
  "risk": "Medium",
  "finding": "2-3 sentence explanation based on what the sample rows show"
}

verdict : Pass (>= 90% comply)  |  Partial (50-89%)  |  Fail (< 50%)
risk    : High (critical breach) | Medium (partial)   | Low (minor gap)
compliance_pct: your best estimate of % compliance across ALL rows based on the sample"""


@dataclass
class RuleVerdict:
    rule_id:         str
    rule_statement:  str
    check_type:      str
    verdict:         str    # Pass / Partial / Fail / Missing
    compliance_pct:  float
    risk:            str    # High / Medium / Low
    total_rows:      int
    pass_count:      int
    fail_count:      int
    missing_count:   int
    finding:         str
    fail_examples:   list[dict] = field(default_factory=list)
    pass_examples:   list[dict] = field(default_factory=list)


def _formula_verdict(fr: FormulaResult, check: RuleCheck) -> RuleVerdict:
    pct = fr.compliance_pct
    if pct >= 90:
        verdict, risk = "Pass",    "Low"
    elif pct >= 50:
        verdict, risk = "Partial", "Medium"
    else:
        verdict, risk = "Fail",    "High"

    finding = (
        f"{fr.passed:,} of {fr.passed + fr.failed:,} applicable rows comply ({pct}%). "
        f"{fr.missing:,} rows had missing data for this check."
    )
    return RuleVerdict(
        rule_id=check.rule_id,
        rule_statement=check.rule.statement,
        check_type="formula",
        verdict=verdict,
        compliance_pct=pct,
        risk=risk,
        total_rows=fr.total,
        pass_count=fr.passed,
        fail_count=fr.failed,
        missing_count=fr.missing,
        finding=finding,
        fail_examples=fr.fail_examples,
        pass_examples=fr.pass_examples,
    )


def _judgment_verdict(jr: JudgmentResult, check: RuleCheck) -> RuleVerdict:
    if not jr.samples:
        return RuleVerdict(
            rule_id=check.rule_id, rule_statement=check.rule.statement,
            check_type="judgment", verdict="Missing", compliance_pct=0.0,
            risk="Medium", total_rows=jr.total_rows,
            pass_count=0, fail_count=0, missing_count=jr.total_rows,
            finding="No usable sample data found in dataset for this rule.",
        )

    samples_text = "\n".join(
        f"Row {i}: " + " | ".join(f"{k}: {v}" for k, v in s.items())
        for i, s in enumerate(jr.samples, 1)
    )

    response = chat(
        [
            {"role": "system", "content": _JUDGMENT_SYSTEM},
            {"role": "user", "content": (
                f"Rule: {check.rule.statement}\n"
                f"Question: {check.judgment_question}\n\n"
                f"Sample ({len(jr.samples)} rows of {jr.total_rows:,} total):\n{samples_text}"
            )},
        ],
        json_mode=True,
    )

    try:
        data    = json.loads(response)
        pct     = float(data.get("compliance_pct", 0))
        verdict = data.get("verdict", "Partial")
        risk    = data.get("risk", "Medium")
        finding = data.get("finding", "")
    except (json.JSONDecodeError, ValueError):
        pct, verdict, risk, finding = 0.0, "Missing", "Medium", "Evaluation failed."

    est_pass = int(jr.total_rows * pct / 100)
    return RuleVerdict(
        rule_id=check.rule_id, rule_statement=check.rule.statement,
        check_type="judgment", verdict=verdict, compliance_pct=pct,
        risk=risk, total_rows=jr.total_rows,
        pass_count=est_pass, fail_count=jr.total_rows - est_pass,
        missing_count=0, finding=finding,
    )


def generate_verdicts(
    detailed_data: DetailedData,
    checks: list[RuleCheck],
    on_progress: Callable[[str], None] | None = None,
) -> list[RuleVerdict]:
    """
    Formula rules → automatic verdict (zero LLM).
    Judgment rules → 1 LLM call per rule.
    Returns all verdicts sorted by compliance % ascending (worst first).
    """
    def log(msg):
        if on_progress: on_progress(msg)

    check_index = {c.rule_id: c for c in checks}
    verdicts: list[RuleVerdict] = []

    for rule_id, fr in detailed_data.formula_results.items():
        check = check_index.get(rule_id)
        if check:
            verdicts.append(_formula_verdict(fr, check))

    for rule_id, jr in detailed_data.judgment_results.items():
        check = check_index.get(rule_id)
        if check:
            log(f"  Evaluating: {rule_id} (judgment)")
            verdicts.append(_judgment_verdict(jr, check))

    verdicts.sort(key=lambda v: v.compliance_pct)
    return verdicts
