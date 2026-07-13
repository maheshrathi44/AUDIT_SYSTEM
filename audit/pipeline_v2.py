"""
Pipeline v2 — full dataset audit with single traversal.

Three-phase design (user reviews between phases):
  Phase 1:
    1. Extract rules from procedures  (LLM)
    2. Map dataset columns            (LLM)
    → pause: user edits column meanings / drops columns

  Phase 2:
    3. Filter rules to applicable ones (LLM)
    → pause: user reviews applicable/dropped rules, edits statements, restores dropped

  Phase 3:
    4. Generate Rule Checks           (LLM, batched)
    4b. Validate columns              (zero LLM)
    5. Single dataset traversal       (zero LLM)
    5b. Post-traversal drop           (zero LLM)
    6. Generate verdicts              (zero LLM for formula; 1 LLM call per judgment)
    7. Write audit report             (LLM)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from audit import confidence, past_observations as po
from audit.engine.traversal import DetailedData, traverse
from audit.engine.verdict import RuleVerdict, generate_verdicts
from audit.extractors import read_excel_raw, read_procedure_file
from audit.llm import extract_rules_llm, map_columns
from audit.llm.report_writer import AuditReport, generate_report
from audit.llm.rule_check_generator import RuleCheck, dict_to_check, generate_rule_checks
from audit.llm.rule_filter import filter_rules
from audit.schemas.rule_schema import DraftRule


@dataclass
class PipelinePhase1Result:
    """Output of Phase 1 — stored in session state for user review before Phase 2."""
    all_rules:           list[DraftRule]
    headers:             list[str]
    rows:                list[dict]
    col_map:             dict
    supported_doc_names: list[str] = field(default_factory=list)
    warnings:            list[str] = field(default_factory=list)
    reused_columns:      int = 0   # columns pre-filled from a Past Observations file
    total_columns:       int = 0
    reused_column_names: set[str] = field(default_factory=set)


@dataclass
class PipelinePhase2Result:
    """Output of Phase 2 (step 3) — stored in session state for user rule review."""
    applicable_rules: list[DraftRule]
    dropped_rules:    dict[str, str]   # rule_id → reason
    reused_rules:     int = 0          # rules pre-decided from a Past Observations file


@dataclass
class PipelineV2Result:
    all_rules:        list[DraftRule]
    applicable_rules: list[DraftRule]
    dropped_rules:    dict[str, str]       # rule_id → reason
    col_map:          dict
    audit_cols:       list[str]
    rule_checks:      list[RuleCheck]
    detailed_data:    DetailedData
    verdicts:         list[RuleVerdict]
    report:           AuditReport
    total_rows:       int
    warnings:         list[str] = field(default_factory=list)


_CASE_ID_MEANING_KEYWORDS = (
    "primary key", "unique identifier", "case id", "record id",
    "unique key", "ticket no", "report no", "ftir no", "unique no",
)


def _find_case_col(headers: list[str], col_map: dict) -> str | None:
    """
    Find the primary-key / case-ID column. Only considers audit-relevant columns.
    First checks semantic_role == "case_id"; if not found, checks meaning text for
    keywords like "primary key", "unique identifier", etc.
    """
    # Pass 1: explicit semantic role — a dataset can have more than one equally-unique
    # reference number (e.g. "SBPR No." alongside "FTIR No."). Prefer the one this
    # audit is actually about (its name contains "ftir") over any other case_id column,
    # instead of just taking whichever happens to appear first in the sheet.
    candidates = [
        h for h in headers
        if col_map.get(h, {}).get("audit_relevant") and col_map.get(h, {}).get("semantic_role") == "case_id"
    ]
    if candidates:
        ftir_candidates = [h for h in candidates if "ftir" in h.lower()]
        return ftir_candidates[0] if ftir_candidates else candidates[0]
    # Pass 2: user described it as primary key / unique identifier in meaning
    for h in headers:
        info = col_map.get(h, {})
        if info.get("audit_relevant"):
            meaning = info.get("meaning", "").lower()
            if any(kw in meaning for kw in _CASE_ID_MEANING_KEYWORDS):
                return h
    return None


def run_pipeline_phase1(
    procedure_paths:    list[str],
    dataset_path:       str,
    supported_doc_names=None,
    on_progress:        Callable[[str], None] | None = None,
    past_observations:  dict | None = None,
) -> PipelinePhase1Result:
    """
    Steps 1-2 only. Returns phase1 result for user review of column meanings.
    past_observations: optional parsed Past Observations file (see audit.past_observations) —
    columns it already covers are pre-filled, skipping the LLM call for those columns.
    """
    warnings: list[str] = []
    supported_doc_names = supported_doc_names or []

    def log(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    log("Step 1/2 — Extracting rules from procedures...")
    all_rules: list[DraftRule] = []
    for path_str in procedure_paths:
        path = Path(path_str)
        log(f"  Reading: {path.name}")
        doc = read_procedure_file(path_str)
        for w in doc.warnings:
            warnings.append(w)
        rules  = extract_rules_llm(doc.text, source_name=path.name, procedure_id=path.stem)
        prefix = path.stem[:8].upper().replace(" ", "_")
        for r in rules:
            r.rule_id = f"{prefix}_{r.rule_id}"
        log(f"  {len(rules)} rules from {path.name}")
        all_rules.extend(rules)
    log(f"  Total: {len(all_rules)} rules extracted")

    log("Step 2/2 — Reading dataset + mapping columns...")
    headers, rows = read_excel_raw(dataset_path)
    log(f"  {len(rows):,} rows loaded, {len(headers)} columns")

    reused_cols = 0
    reused_col_names: set[str] = set()
    if past_observations:
        reused_col_map, remaining_headers = po.split_columns(past_observations, headers)
        reused_cols      = len(reused_col_map)
        reused_col_names = set(reused_col_map.keys())
        new_col_map = map_columns(remaining_headers, rows) if remaining_headers else {}
        col_map = {**reused_col_map, **new_col_map}
        if reused_cols:
            log(f"  {reused_cols}/{len(headers)} columns reused from past observations, "
                f"{len(remaining_headers)} sent to AI")
    else:
        col_map = map_columns(headers, rows)
    log(f"  Column mapping complete — review and edit before proceeding")

    return PipelinePhase1Result(
        all_rules=all_rules,
        headers=headers,
        rows=rows,
        col_map=col_map,
        supported_doc_names=supported_doc_names,
        warnings=warnings,
        reused_columns=reused_cols,
        total_columns=len(headers),
        reused_column_names=reused_col_names,
    )


def run_pipeline_phase2(
    phase1:            PipelinePhase1Result,
    col_map:            dict,
    on_progress:        Callable[[str], None] | None = None,
    past_observations:  dict | None = None,
) -> PipelinePhase2Result:
    """
    Step 3 only — filter rules. Returns phase2 result for user rule review.
    past_observations: rules it already has an applicable/dropped decision for
    (matched by rule_id + statement) skip the LLM filter call.
    """
    def log(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    log("Filtering rules applicable to this dataset...")

    reused_count = 0
    if past_observations:
        reused_app, reused_dropped, remaining_rules = po.split_rules(past_observations, phase1.all_rules)
        new_applicable, new_dropped = filter_rules(remaining_rules, col_map) if remaining_rules else ([], {})
        applicable_rules = reused_app + new_applicable
        dropped          = {**reused_dropped, **new_dropped}
        reused_count     = len(reused_app) + len(reused_dropped)
        if reused_count:
            log(f"  {reused_count}/{len(phase1.all_rules)} rules reused from past observations, "
                f"{len(remaining_rules)} sent to AI for filtering")
    else:
        applicable_rules, dropped = filter_rules(phase1.all_rules, col_map)

    log(f"  {len(applicable_rules)} applicable, {len(dropped)} dropped — review before proceeding")
    return PipelinePhase2Result(
        applicable_rules=applicable_rules, dropped_rules=dropped, reused_rules=reused_count,
    )


@dataclass
class PipelinePhase3Result:
    """Output of Phase 3 (step 4) — stored for user rule-check review."""
    rule_checks:      list[RuleCheck]
    dropped_rules:    dict[str, str]
    applicable_rules: list[DraftRule]
    audit_cols:       list[str]        # audit-relevant column names for UI selectors
    reused_checks:    int = 0          # rule checks pre-filled from a Past Observations file


def run_pipeline_phase3(
    phase1:            PipelinePhase1Result,
    col_map:            dict,
    applicable_rules:   list[DraftRule],
    dropped_rules:      dict[str, str],
    on_progress:        Callable[[str], None] | None = None,
    past_observations:  dict | None = None,
) -> PipelinePhase3Result:
    """
    Step 4 — generate + validate rule checks. Returns for user review.
    past_observations: rules it already has a computation spec for (matched by
    rule_id) skip the LLM rule-check-generation call.
    """
    headers = phase1.headers

    def log(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    audit_col_map = {k: v for k, v in col_map.items() if v.get("audit_relevant")}
    audit_set     = set(audit_col_map.keys())
    header_set    = set(headers)
    audit_cols    = [h for h in headers if h in audit_set]

    log("Generating Rule Checks (batched LLM calls)...")
    reused_count = 0
    if past_observations:
        reused_dicts, remaining_rules = po.split_rule_checks(past_observations, applicable_rules)
        rule_index    = {r.rule_id: r for r in applicable_rules}
        reused_checks = [
            dict_to_check(d, rule_index[d["rule_id"]])
            for d in reused_dicts if d.get("rule_id") in rule_index
        ]
        reused_count  = len(reused_checks)
        new_checks    = (
            generate_rule_checks(remaining_rules, audit_col_map, supported_doc_names=phase1.supported_doc_names)
            if remaining_rules else []
        )
        rule_checks = reused_checks + new_checks
        if reused_count:
            log(f"  {reused_count}/{len(applicable_rules)} rule checks reused from past observations, "
                f"{len(remaining_rules)} generated by AI")
    else:
        rule_checks = generate_rule_checks(
            applicable_rules, audit_col_map,
            supported_doc_names=phase1.supported_doc_names,
        )

    valid_checks: list[RuleCheck] = []
    for check in rule_checks:
        if check.check_type == "formula":
            if not check.column_a or check.column_a not in header_set:
                dropped_rules[check.rule_id] = (
                    f"required column '{check.column_a or 'unknown'}' not found in dataset"
                )
                continue
            if check.column_a not in audit_set:
                dropped_rules[check.rule_id] = (
                    f"column '{check.column_a}' was excluded from audit by user"
                )
                continue
            if check.column_b and check.column_b not in header_set:
                dropped_rules[check.rule_id] = (
                    f"required column '{check.column_b}' not found in dataset"
                )
                continue
            if check.column_b and check.column_b not in audit_set:
                check.column_b = ""
            if check.filter_column and check.filter_column not in header_set:
                check.filter_column = ""
                check.filter_value  = ""
        elif check.check_type == "judgment":
            valid_samples = [c for c in check.sample_columns if c in audit_set]
            if not valid_samples:
                dropped_rules[check.rule_id] = "no audit-relevant sample columns found in dataset"
                continue
            check.sample_columns = valid_samples
        valid_checks.append(check)

    valid_ids        = {c.rule_id for c in valid_checks}
    applicable_rules = [r for r in applicable_rules if r.rule_id in valid_ids]
    f_count = sum(1 for c in valid_checks if c.check_type == "formula")
    j_count = sum(1 for c in valid_checks if c.check_type == "judgment")
    log(f"  {f_count} formula checks, {j_count} judgment checks — review before proceeding")

    return PipelinePhase3Result(
        rule_checks=valid_checks,
        dropped_rules=dropped_rules,
        applicable_rules=applicable_rules,
        audit_cols=audit_cols,
        reused_checks=reused_count,
    )


def _attach_confidence_tally(
    verdicts:          list[RuleVerdict],
    rule_checks:       list[RuleCheck],
    past_observations: dict | None,
) -> None:
    """
    Seeds each verdict's confirm/disagree tally (mutates in place, after verdicts
    already exist — does not affect how any verdict itself was computed):
      - a saved tally in Past Audit Settings is carried over exactly as-is
      - otherwise, a rule from a Past Audit Report starts seeded straight to High
      - otherwise, starts neutral (Medium)
    """
    rule_by_id = {c.rule_id: c.rule for c in rule_checks}
    for v in verdicts:
        saved = po.get_confidence_tally(past_observations, v.rule_id)
        if saved is not None:
            v.confirm_count, v.disagree_count = saved
        else:
            rule = rule_by_id.get(v.rule_id)
            v.confirm_count, v.disagree_count = confidence.seed_tally(
                is_manual=bool(getattr(rule, "is_manual", False))
            )


def run_pipeline_phase4(
    phase1:            PipelinePhase1Result,
    col_map:            dict,
    rule_checks:        list[RuleCheck],
    applicable_rules:   list[DraftRule],
    dropped_rules:      dict[str, str],
    on_progress:        Callable[[str], None] | None = None,
    past_observations:  dict | None = None,
) -> PipelineV2Result:
    """Steps 5-7 — traverse, verdicts, report. Takes user-edited rule checks."""
    warnings = list(phase1.warnings)
    headers  = phase1.headers
    rows     = phase1.rows
    audit_cols = [h for h in headers if col_map.get(h, {}).get("audit_relevant")]

    def log(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    case_col     = _find_case_col(headers, col_map)
    context_cols = [case_col] if case_col else []

    log(f"Step 1/3 — Traversing {len(rows):,} rows (zero LLM)...")
    detailed_data = traverse(rows, rule_checks, context_columns=context_cols)

    evaluable: list[RuleCheck] = []
    for check in rule_checks:
        if check.check_type == "formula":
            fr = detailed_data.formula_results.get(check.rule_id)
            if fr and fr.total > 0 and fr.passed == 0 and fr.failed == 0:
                dropped_rules[check.rule_id] = (
                    f"all {fr.total} rows returned missing — "
                    f"filter condition never matched or column produced no evaluable values"
                )
                continue
        evaluable.append(check)
    rule_checks = evaluable
    valid_ids = {c.rule_id for c in rule_checks}
    applicable_rules = [r for r in applicable_rules if r.rule_id in valid_ids]
    log("  Traversal complete")

    log("Step 2/3 — Generating verdicts...")
    verdicts = generate_verdicts(detailed_data, rule_checks, on_progress=log)
    log(f"  {len(verdicts)} verdicts generated")
    _attach_confidence_tally(verdicts, rule_checks, past_observations)

    log("Step 3/3 — Writing audit report...")
    report = generate_report(verdicts)
    log("  Done")

    return PipelineV2Result(
        all_rules=phase1.all_rules,
        applicable_rules=applicable_rules,
        dropped_rules=dropped_rules,
        col_map=col_map,
        audit_cols=audit_cols,
        rule_checks=rule_checks,
        detailed_data=detailed_data,
        verdicts=verdicts,
        report=report,
        total_rows=len(rows),
        warnings=warnings,
    )


def run_pipeline_v2(
    procedure_paths:     list[str],
    dataset_path:        str,
    supported_doc_names=None,
    on_progress:         Callable[[str], None] | None = None,
) -> PipelineV2Result:
    warnings: list[str] = []
    supported_doc_names = supported_doc_names or []

    def log(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    # ── Step 1: Rule extraction ────────────────────────────────────────────
    log("Step 1/7 — Extracting rules from procedures...")
    all_rules: list[DraftRule] = []
    for path_str in procedure_paths:
        path = Path(path_str)
        log(f"  Reading: {path.name}")
        doc = read_procedure_file(path_str)
        for w in doc.warnings:
            warnings.append(w)
        rules  = extract_rules_llm(doc.text, source_name=path.name, procedure_id=path.stem)
        prefix = path.stem[:8].upper().replace(" ", "_")
        for r in rules:
            r.rule_id = f"{prefix}_{r.rule_id}"
        log(f"  {len(rules)} rules from {path.name}")
        all_rules.extend(rules)
    log(f"  Total: {len(all_rules)} rules extracted")

    # ── Step 2: Column mapping ─────────────────────────────────────────────
    log("Step 2/7 — Reading dataset + mapping columns...")
    headers, rows = read_excel_raw(dataset_path)
    log(f"  {len(rows):,} rows loaded, {len(headers)} columns")
    col_map    = map_columns(headers, get_sample_rows(rows))
    audit_cols = [h for h in headers if col_map.get(h, {}).get("audit_relevant")]
    log(f"  {len(audit_cols)} audit-relevant columns identified")

    # ── Step 3: Rule filtering ─────────────────────────────────────────────
    log(f"Step 3/7 — Filtering rules applicable to this dataset...")
    applicable_rules, dropped = filter_rules(all_rules, col_map)
    log(f"  {len(applicable_rules)} applicable, {len(dropped)} dropped")

    # ── Step 4: Rule Check generation ─────────────────────────────────────
    log(f"Step 4/7 — Generating Rule Checks (batched LLM calls)...")
    rule_checks = generate_rule_checks(
        applicable_rules, col_map,
        supported_doc_names=supported_doc_names,
    )

    # ── Step 4b: Column validation — drop checks with missing columns ──────
    header_set = set(headers)
    valid_checks: list[RuleCheck] = []
    for check in rule_checks:
        if check.check_type == "formula":
            # column_a is mandatory
            if not check.column_a or check.column_a not in header_set:
                dropped[check.rule_id] = (
                    f"required column '{check.column_a or 'unknown'}' not found in dataset"
                )
                continue
            # column_b must exist if specified
            if check.column_b and check.column_b not in header_set:
                dropped[check.rule_id] = (
                    f"required column '{check.column_b}' not found in dataset"
                )
                continue
            # filter_column missing → remove the filter but keep the rule
            if check.filter_column and check.filter_column not in header_set:
                check.filter_column = ""
                check.filter_value  = ""
        elif check.check_type == "judgment":
            valid_samples = [c for c in check.sample_columns if c in header_set]
            if not valid_samples:
                dropped[check.rule_id] = "no sample columns found in dataset"
                continue
            check.sample_columns = valid_samples

        valid_checks.append(check)

    rule_checks = valid_checks
    valid_ids   = {c.rule_id for c in rule_checks}
    applicable_rules = [r for r in applicable_rules if r.rule_id in valid_ids]
    f_count = sum(1 for c in rule_checks if c.check_type == "formula")
    j_count = sum(1 for c in rule_checks if c.check_type == "judgment")
    log(f"  {f_count} formula checks, {j_count} judgment checks ({len(dropped)} total dropped)")

    # identify case_id column for richer fail/pass examples
    case_col = next(
        (h for h in headers if col_map.get(h, {}).get("semantic_role") == "case_id"),
        None,
    )
    context_cols = [case_col] if case_col else []

    # ── Step 5: Single dataset traversal ──────────────────────────────────
    log(f"Step 5/7 — Traversing {len(rows):,} rows (zero LLM)...")
    detailed_data = traverse(rows, rule_checks, context_columns=context_cols)
    log("  Traversal complete")

    # ── Step 6: Verdicts ───────────────────────────────────────────────────
    log("Step 6/7 — Generating verdicts...")
    verdicts = generate_verdicts(detailed_data, rule_checks, on_progress=log)
    log(f"  {len(verdicts)} verdicts generated")

    # ── Step 7: Report ─────────────────────────────────────────────────────
    log("Step 7/7 — Writing audit report...")
    report = generate_report(verdicts)
    log("  Done")

    return PipelineV2Result(
        all_rules=all_rules,
        applicable_rules=applicable_rules,
        dropped_rules=dropped,
        col_map=col_map,
        audit_cols=audit_cols,
        rule_checks=rule_checks,
        detailed_data=detailed_data,
        verdicts=verdicts,
        report=report,
        total_rows=len(rows),
        warnings=warnings,
    )
