"""
Single dataset traversal — executes all Rule Checks in ONE pass through all rows.
Zero LLM calls. Pure Python.
Produces DetailedData: aggregates for formula rules, samples for judgment rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from audit.llm.rule_check_generator import RuleCheck

MAX_SAMPLES  = 20   # max sample rows collected per judgment rule
MAX_EXAMPLES = 5    # max fail examples stored per formula rule


# ── date / number helpers ──────────────────────────────────────────────────────

_DATE_FORMATS = (
    "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y",
    "%d/%b/%Y", "%d-%b-%Y", "%d %b %Y", "%d %B %Y",
)

def _parse_date(val: str) -> datetime | None:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(val.strip(), fmt)
        except ValueError:
            continue
    return None


# ── result containers ──────────────────────────────────────────────────────────

@dataclass
class FormulaResult:
    rule_id: str
    total:   int = 0
    passed:  int = 0
    failed:  int = 0
    missing: int = 0
    fail_examples: list[dict] = field(default_factory=list)

    @property
    def compliance_pct(self) -> float:
        # missing = no data to check → not a violation, count as passing
        return round(100 * (self.passed + self.missing) / self.total, 1) if self.total else 0.0


@dataclass
class JudgmentResult:
    rule_id:    str
    total_rows: int = 0
    samples:    list[dict] = field(default_factory=list)


@dataclass
class DetailedData:
    formula_results:  dict[str, FormulaResult]  = field(default_factory=dict)
    judgment_results: dict[str, JudgmentResult] = field(default_factory=dict)
    total_rows: int = 0


# ── per-row formula execution ──────────────────────────────────────────────────

def _run_formula(row: dict, check: RuleCheck) -> str:
    """Returns 'pass', 'fail', or 'missing'."""
    val_a = row.get(check.column_a, "").strip()
    val_b = row.get(check.column_b, "").strip() if check.column_b else ""
    comp  = check.computation

    if comp == "date_difference":
        d_a = _parse_date(val_a)
        d_b = _parse_date(val_b)
        if not d_a or not d_b:
            return "missing"
        diff = abs((d_b - d_a).days)
        thr  = check.threshold or 0
        cond = check.pass_condition.strip()
        if "<=" in cond:
            return "pass" if diff <= thr else "fail"
        if ">=" in cond:
            return "pass" if diff >= thr else "fail"
        return "missing"

    if comp == "not_blank":
        return "pass" if val_a else "fail"

    if comp == "is_blank":
        return "pass" if not val_a else "fail"

    if comp == "value_contains":
        keyword = check.pass_condition.lower().strip()
        return "pass" if keyword in val_a.lower() else ("missing" if not val_a else "fail")

    return "missing"


# ── main traversal ─────────────────────────────────────────────────────────────

def traverse(
    rows: list[dict[str, str]],
    checks: list[RuleCheck],
) -> DetailedData:
    """
    Single pass through all rows.
    Executes formula checks and collects samples for judgment checks.
    No LLM. Returns DetailedData.
    """
    formula_checks   = [c for c in checks if c.check_type == "formula"]
    judgment_checks  = [c for c in checks if c.check_type == "judgment"]

    f_results: dict[str, FormulaResult] = {
        c.rule_id: FormulaResult(rule_id=c.rule_id) for c in formula_checks
    }
    j_results: dict[str, JudgmentResult] = {
        c.rule_id: JudgmentResult(rule_id=c.rule_id) for c in judgment_checks
    }

    for row in rows:
        for check in formula_checks:
            fr = f_results[check.rule_id]
            fr.total += 1
            result = _run_formula(row, check)
            if result == "pass":
                fr.passed += 1
            elif result == "fail":
                fr.failed += 1
                if len(fr.fail_examples) < MAX_EXAMPLES:
                    fr.fail_examples.append({
                        k: row.get(k, "")
                        for k in [check.column_a, check.column_b] if k
                    })
            else:
                fr.missing += 1

        for check in judgment_checks:
            jr = j_results[check.rule_id]
            jr.total_rows += 1
            if len(jr.samples) < MAX_SAMPLES:
                sample = {
                    col: row.get(col, "")
                    for col in check.sample_columns
                    if row.get(col, "").strip()
                }
                if sample:
                    jr.samples.append(sample)

    return DetailedData(
        formula_results=f_results,
        judgment_results=j_results,
        total_rows=len(rows),
    )
