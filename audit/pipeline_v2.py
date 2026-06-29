"""
Pipeline v2 — full dataset audit with single traversal.

Flow:
  1. Extract rules from procedures        (LLM — one call per procedure)
  2. Map dataset columns                  (LLM, once)
  3. Filter rules to applicable ones      (LLM, once)
  4. Generate Rule Checks                 (LLM, batched ~4 calls)
  5. Single dataset traversal             (zero LLM — pure Python)
  6. Generate verdicts                    (zero LLM for formula; 1 call per judgment rule)
  7. Write audit report                   (LLM, once)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from audit.engine.traversal import DetailedData, traverse
from audit.engine.verdict import RuleVerdict, generate_verdicts
from audit.extractors import get_sample_rows, read_excel_raw, read_procedure_file
from audit.llm import extract_rules_llm, map_columns
from audit.llm.report_writer import AuditReport, generate_report
from audit.llm.rule_check_generator import RuleCheck, generate_rule_checks
from audit.llm.rule_filter import filter_rules
from audit.schemas.rule_schema import DraftRule


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
    f_count = sum(1 for c in rule_checks if c.check_type == "formula")
    j_count = sum(1 for c in rule_checks if c.check_type == "judgment")
    log(f"  {f_count} formula checks, {j_count} judgment checks")

    # ── Step 5: Single dataset traversal ──────────────────────────────────
    log(f"Step 5/7 — Traversing {len(rows):,} rows (zero LLM)...")
    detailed_data = traverse(rows, rule_checks)
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
