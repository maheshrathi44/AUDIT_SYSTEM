"""
Verdict generator — produces final audit result per rule from DetailedData.
Formula rules: automatic (zero LLM).
Judgment rules: 1 LLM call per rule (small input — just samples).
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from typing import Callable

from audit.engine.traversal import DetailedData, FormulaResult, JudgmentResult
from audit.llm.client import chat
from audit.llm.rule_check_generator import RuleCheck

# A judgment rule's sample column(s) are often low-cardinality (Status, Reason,
# Category, ...) — many rows share the exact same value. Rows with identical
# sample-column values get the identical question asked of the identical text,
# so (with temperature=0) they get the identical verdict. GROUP_CAP is how many
# distinct value-combinations get judged individually and then applied back to
# every row that shares them — this is deduplication, not sampling: it loses
# nothing as long as a combination actually repeats.
# Only once there are MORE distinct combinations than this does a real long tail
# exist — TAIL_SAMPLE_CAP is the extra budget spent sampling that tail directly,
# with the (much smaller) unsampled remainder estimated from that sample's own
# pass/fail ratio. Both keep the LLM call's size bounded regardless of row count.
GROUP_CAP       = 75
TAIL_SAMPLE_CAP = 75

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

    # Confidence tally — set afterward by pipeline_v2 (not by this file); left at
    # neutral defaults here so nothing that constructs a RuleVerdict needs to change.
    confirm_count:   int = 0
    disagree_count:  int = 0


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

    cols = check.sample_columns or []

    # ── Group identical rows together — exact dedup, not sampling ───────────────
    groups: dict[tuple, list[dict]] = {}
    for row in jr.samples:
        key = tuple(row.get(c, "") for c in cols)
        groups.setdefault(key, []).append(row)

    # Most-frequent combinations first, so the head cap covers as many real rows
    # as possible exactly, before any estimation is needed at all.
    ordered = sorted(groups.values(), key=len, reverse=True)
    head = ordered[:GROUP_CAP]
    tail_rows_flat = [row for rows in ordered[GROUP_CAP:] for row in rows]

    # Items actually sent to the LLM: one representative row per head group (its
    # verdict applies to every row that shares that group), plus — only if a long
    # tail exists — a random sample of individual tail rows judged on their own.
    items:         list[dict] = [rows[0] for rows in head]
    item_weights:  list[int]  = [len(rows) for rows in head]
    n_head_items = len(items)

    tail_sample: list[dict] = []
    if tail_rows_flat:
        random.shuffle(tail_rows_flat)
        tail_sample = tail_rows_flat[:TAIL_SAMPLE_CAP]
        items.extend(tail_sample)
        item_weights.extend([1] * len(tail_sample))
    remaining_tail_rows = tail_rows_flat[len(tail_sample):]

    rows_text = "\n".join(
        f"Row {i}: " + " | ".join(f"{k}: {v}" for k, v in item.items())
        for i, item in enumerate(items)
    )

    response = chat(
        [
            {"role": "system", "content": _JUDGMENT_SYSTEM},
            {"role": "user", "content": (
                f"Rule: {check.rule.statement}\n"
                f"Question: {check.judgment_question}\n\n"
                f"Evaluate each of these {len(items):,} rows "
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

    # head_* counts are exact (each already scaled by how many real rows share that
    # group). tail_sample_* counts are exact for the tail rows actually judged.
    head_pass = head_fail = head_indet = 0
    tail_sample_pass = tail_sample_fail = tail_sample_indet = 0
    fail_examples: list[dict] = []
    pass_examples: list[dict] = []
    indet_examples: list[dict] = []

    for ev in evaluations:
        idx = ev.get("row_index", -1)
        if not (0 <= idx < len(items)):
            continue
        v      = ev.get("verdict") or "indeterminate"
        if isinstance(v, list):
            v = v[0] if v else "indeterminate"
        v      = str(v).strip().lower()
        row    = items[idx]
        weight = item_weights[idx]
        is_head = idx < n_head_items

        if v == "pass":
            head_pass += weight if is_head else 0
            tail_sample_pass += 0 if is_head else 1
            if len(pass_examples) < 3: pass_examples.append(row)
        elif v == "fail":
            head_fail += weight if is_head else 0
            tail_sample_fail += 0 if is_head else 1
            if len(fail_examples) < 5: fail_examples.append(row)
        else:
            head_indet += weight if is_head else 0
            tail_sample_indet += 0 if is_head else 1
            if len(indet_examples) < 3: indet_examples.append(row)

    # Extrapolate the unsampled remainder of the tail from the tail sample's own
    # pass/fail/indeterminate split — proportional to real judged evidence, not a
    # guess. If the tail sample itself produced nothing usable, the remainder is
    # counted as indeterminate (missing) rather than assumed either way.
    extra_pass = extra_fail = extra_indet = 0
    n_remaining = len(remaining_tail_rows)
    if n_remaining:
        tail_judged = tail_sample_pass + tail_sample_fail + tail_sample_indet
        if tail_judged:
            extra_pass  = round(n_remaining * tail_sample_pass / tail_judged)
            extra_fail  = round(n_remaining * tail_sample_fail / tail_judged)
            extra_indet = n_remaining - extra_pass - extra_fail
        else:
            extra_indet = n_remaining

    pass_count = head_pass + tail_sample_pass + extra_pass
    fail_count = head_fail + tail_sample_fail + extra_fail
    indet_count = head_indet + tail_sample_indet + extra_indet

    evaluated = pass_count + fail_count
    pct       = round(100 * pass_count / evaluated, 1) if evaluated else 0.0

    if pct >= 90:   verdict_str = "Pass"
    elif pct >= 50: verdict_str = "Partial"
    else:           verdict_str = "Fail"

    # missing = filter-excluded rows + rows LLM couldn't (or didn't) evaluate
    total_missing = jr.missing + indet_count

    return RuleVerdict(
        rule_id=check.rule_id, rule_statement=check.rule.statement,
        check_type="judgment", verdict=verdict_str, compliance_pct=pct,
        risk=risk, total_rows=jr.total_rows,
        pass_count=pass_count, fail_count=fail_count,
        missing_count=total_missing,
        finding=finding,
        fail_examples=fail_examples,
        pass_examples=pass_examples,
        miss_examples=indet_examples,
        samples=jr.samples,   # all applicable rows, ungrouped — for "view all" expander
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
