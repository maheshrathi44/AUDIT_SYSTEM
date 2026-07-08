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
You are an auditor. Given a rule and a list of data rows, classify EACH row individually.

Return ONLY valid JSON:
{
  "evaluations": [
    {"row_index": 0, "verdict": "pass"},
    {"row_index": 1, "verdict": "fail"},
    {"row_index": 2, "verdict": "indeterminate"}
  ],
  "finding": "2-3 sentence overall summary of what the data shows",
  "risk": "Medium"
}

verdict per row — choose exactly one:
  "pass"          — this row complies with the rule
  "fail"          — this row violates the rule
  "indeterminate" — insufficient evidence in this row to decide

risk (for the overall finding): High | Medium | Low
You MUST return one evaluation object per row, using the exact row_index from the input."""


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
    miss_examples:   list[dict] = field(default_factory=list)
    samples:         list[dict] = field(default_factory=list)  # judgment only


def _formula_verdict(fr: FormulaResult, check: RuleCheck) -> RuleVerdict:
    pct = fr.compliance_pct
    if pct >= 90:
        verdict, risk = "Pass",    "Low"
    elif pct >= 50:
        verdict, risk = "Partial", "Medium"
    else:
        verdict, risk = "Fail",    "High"

    applicable   = fr.passed + fr.failed
    non_comp_pct = round(100 - pct, 1)
    finding = (
        f"{fr.failed:,} of {applicable:,} evaluated rows are non-compliant ({non_comp_pct}%). "
        f"{fr.missing:,} rows skipped (filter not triggered or data not available — not counted)."
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
        miss_examples=fr.miss_examples,
    )


def _judgment_verdict(jr: JudgmentResult, check: RuleCheck) -> RuleVerdict:
    """
    Per-row LLM evaluation — every applicable row is classified pass/fail/indeterminate.
    Produces actual fail_examples and pass_examples just like formula rules.
    """
    if not jr.samples:
        finding = (
            "No usable data found for this rule."
            if jr.missing == 0
            else f"All {jr.total_rows:,} rows did not match the filter — none were applicable."
        )
        return RuleVerdict(
            rule_id=check.rule_id, rule_statement=check.rule.statement,
            check_type="judgment", verdict="Missing", compliance_pct=0.0,
            risk="Medium", total_rows=jr.total_rows,
            pass_count=0, fail_count=0, missing_count=jr.missing,
            finding=finding,
        )

    # 0-based row indices so LLM row_index maps directly to jr.samples list
    rows_text = "\n".join(
        f"Row {i}: " + " | ".join(f"{k}: {v}" for k, v in s.items())
        for i, s in enumerate(jr.samples)
    )

    response = chat(
        [
            {"role": "system", "content": _JUDGMENT_SYSTEM},
            {"role": "user", "content": (
                f"Rule: {check.rule.statement}\n"
                f"Question: {check.judgment_question}\n\n"
                f"Evaluate each of these {len(jr.samples):,} rows "
                f"({jr.missing:,} rows excluded by filter):\n\n"
                f"{rows_text}"
            )},
        ],
        json_mode=True,
    )

    try:
        data        = json.loads(response)
        evaluations = data.get("evaluations", [])
        finding     = data.get("finding", "")
        risk        = data.get("risk", "Medium")
    except (json.JSONDecodeError, ValueError):
        evaluations, finding, risk = [], "Evaluation failed.", "Medium"

    # Map per-row verdicts back to actual row dicts
    pass_rows:  list[dict] = []
    fail_rows:  list[dict] = []
    indet_rows: list[dict] = []
    for ev in evaluations:
        idx = ev.get("row_index", -1)
        if 0 <= idx < len(jr.samples):
            v = (ev.get("verdict") or "indeterminate").strip().lower()
            if v == "pass":
                pass_rows.append(jr.samples[idx])
            elif v == "fail":
                fail_rows.append(jr.samples[idx])
            else:
                indet_rows.append(jr.samples[idx])

    pass_count = len(pass_rows)
    fail_count = len(fail_rows)
    evaluated  = pass_count + fail_count
    pct        = round(100 * pass_count / evaluated, 1) if evaluated else 0.0

    if pct >= 90:   verdict_str = "Pass"
    elif pct >= 50: verdict_str = "Partial"
    else:           verdict_str = "Fail"

    # missing = filter-excluded rows + rows LLM couldn't evaluate
    total_missing = jr.missing + len(indet_rows)

    return RuleVerdict(
        rule_id=check.rule_id, rule_statement=check.rule.statement,
        check_type="judgment", verdict=verdict_str, compliance_pct=pct,
        risk=risk, total_rows=jr.total_rows,
        pass_count=pass_count, fail_count=fail_count,
        missing_count=total_missing,
        finding=finding,
        fail_examples=fail_rows[:5],
        pass_examples=pass_rows[:5],
        miss_examples=indet_rows[:5],
        samples=jr.samples,   # all applicable rows for "view all" expander
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
