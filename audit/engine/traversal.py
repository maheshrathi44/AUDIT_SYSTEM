"""
Single dataset traversal — executes all Rule Checks in ONE pass through all rows.
Zero LLM calls. Pure Python.
Produces DetailedData: aggregates for formula rules, samples for judgment rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from dateutil.parser import parse as _dateutil_parse
from dateutil.parser import ParserError

from audit.llm.rule_check_generator import RuleCheck

MAX_EXAMPLES      = 5   # max fail examples per formula rule
MAX_PASS_EXAMPLES = 3   # max pass examples per formula rule
MAX_MISS_EXAMPLES = 3   # max missing examples per formula rule


# ── date parsing ───────────────────────────────────────────────────────────────

# ISO-style YYYY-MM-DD or YYYY/MM/DD — year is first, do NOT apply dayfirst
_ISO_DATE_RE = re.compile(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}')

def _parse_date(val: str) -> datetime | None:
    """Parse any date string. Handles any format via dateutil."""
    v = val.strip()
    if not v:
        return None
    try:
        if _ISO_DATE_RE.match(v):
            return _dateutil_parse(v, yearfirst=True, dayfirst=False)
        return _dateutil_parse(v, dayfirst=True)
    except (ParserError, OverflowError, ValueError):
        return None


# ── result containers ──────────────────────────────────────────────────────────

@dataclass
class FormulaResult:
    rule_id:       str
    total:         int = 0
    passed:        int = 0
    failed:        int = 0
    missing:       int = 0
    fail_examples: list[dict] = field(default_factory=list)
    pass_examples: list[dict] = field(default_factory=list)
    miss_examples: list[dict] = field(default_factory=list)

    @property
    def compliance_pct(self) -> float:
        # Only rows that were actually evaluated (pass or fail) count toward compliance.
        # Missing rows (filter not triggered, blank data) are excluded from both numerator and denominator.
        applicable = self.passed + self.failed
        return round(100 * self.passed / applicable, 1) if applicable else 0.0


@dataclass
class JudgmentResult:
    rule_id:    str
    total_rows: int = 0
    missing:    int = 0   # rows where filter condition didn't apply
    samples:    list[dict] = field(default_factory=list)


@dataclass
class DetailedData:
    formula_results:  dict[str, FormulaResult]  = field(default_factory=dict)
    judgment_results: dict[str, JudgmentResult] = field(default_factory=dict)
    total_rows: int = 0


# ── per-row formula execution ──────────────────────────────────────────────────

def _row_matches_condition(row: dict, col: str, val: str) -> bool:
    """True if the row satisfies a single column=value condition."""
    actual = str(row.get(col) or "").strip()
    if val == "(blank)":
        return not actual
    if val == "(not blank)":
        return bool(actual)
    return actual.lower() == val.lower()


def _filter_applies(row: dict, check: RuleCheck) -> bool:
    """
    Returns True if this row should be EVALUATED (filter conditions are all satisfied).
    Returns False if the row doesn't match the filter → treated as 'missing'.

    Priority: filter_conditions list (AND logic) → single filter_column/filter_value fallback.
    """
    conditions = check.filter_conditions
    if conditions:
        return all(
            _row_matches_condition(row, c.get("column", ""), c.get("value", ""))
            for c in conditions
            if c.get("column") and c.get("value")
        )
    if check.filter_column and check.filter_value:
        return _row_matches_condition(row, check.filter_column, check.filter_value)
    return True  # no filter — evaluate all rows


def _run_formula(row: dict, check: RuleCheck) -> str:
    """
    Returns 'pass', 'fail', or 'missing'.

    Rows that don't satisfy the filter conditions return 'missing'
    (excluded from compliance denominator).
    """
    # ── Conditional filter ────────────────────────────────────────────────────
    if not _filter_applies(row, check):
        return "missing"

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


def _example_row(row: dict, check: RuleCheck, context_columns: list[str]) -> dict:
    """Build a compact example dict with context + formula columns."""
    cols = list(dict.fromkeys(
        context_columns
        + ([check.filter_column] if check.filter_column else [])
        + ([check.column_a]      if check.column_a      else [])
        + ([check.column_b]      if check.column_b      else [])
    ))
    return {k: row.get(k, "") for k in cols if k}


# ── main traversal ─────────────────────────────────────────────────────────────

def traverse(
    rows: list[dict[str, str]],
    checks: list[RuleCheck],
    context_columns: list[str] | None = None,
) -> DetailedData:
    """
    Single pass through all rows.
    Executes formula checks and collects samples for judgment checks.
    No LLM. Returns DetailedData.
    context_columns: extra columns (e.g. case_id) included in fail/pass examples.
    """
    ctx             = context_columns or []
    formula_checks  = [c for c in checks if c.check_type == "formula"]
    judgment_checks = [c for c in checks if c.check_type == "judgment"]

    f_results: dict[str, FormulaResult] = {
        c.rule_id: FormulaResult(rule_id=c.rule_id) for c in formula_checks
    }
    j_results: dict[str, JudgmentResult] = {
        c.rule_id: JudgmentResult(rule_id=c.rule_id) for c in judgment_checks
    }

    for row in rows:
        for check in formula_checks:
            fr     = f_results[check.rule_id]
            fr.total += 1
            result = _run_formula(row, check)

            if result == "pass":
                fr.passed += 1
                if len(fr.pass_examples) < MAX_PASS_EXAMPLES:
                    fr.pass_examples.append(_example_row(row, check, ctx))
            elif result == "fail":
                fr.failed += 1
                if len(fr.fail_examples) < MAX_EXAMPLES:
                    fr.fail_examples.append(_example_row(row, check, ctx))
            else:
                fr.missing += 1
                if len(fr.miss_examples) < MAX_MISS_EXAMPLES:
                    fr.miss_examples.append(_example_row(row, check, ctx))

        for check in judgment_checks:
            jr = j_results[check.rule_id]
            jr.total_rows += 1

            # Apply filter — rows that don't match go to missing, not samples
            if not _filter_applies(row, check):
                jr.missing += 1
                continue

            # Collect ALL applicable rows — no sampling cap
            sample = {
                col: row.get(col, "")
                for col in (ctx + check.sample_columns)
                if row.get(col, "").strip()
            }
            if sample:
                jr.samples.append(sample)

    return DetailedData(
        formula_results=f_results,
        judgment_results=j_results,
        total_rows=len(rows),
    )
