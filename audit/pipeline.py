"""
Core audit pipeline — returns structured results instead of printing.
Used by both the CLI runner (run_audit.py) and the Streamlit frontend (app.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from audit.extractors import get_sample_rows, read_excel_raw, read_procedure_file
from audit.llm import audit_row, extract_rules_llm, map_columns, match_rules_for_row
from audit.llm.auditor import RowFinding
from audit.llm.rule_matcher import RelevantRule
from audit.schemas.rule_schema import DraftRule


@dataclass
class RowAuditResult:
    index: int
    row_id: str
    row_data: dict[str, str]
    matched: list[RelevantRule]
    finding: RowFinding


@dataclass
class AuditResult:
    rules: list[DraftRule]
    headers: list[str]
    col_map: dict
    audit_cols: list[str]
    row_results: list[RowAuditResult]
    warnings: list[str] = field(default_factory=list)


def run_pipeline(
    procedure_paths: list[str],
    dataset_path: str,
    max_rows: int = 4,
    on_progress: Callable[[str], None] | None = None,
) -> AuditResult:
    """
    Run the full audit pipeline and return structured results.
    on_progress: optional callback called with status messages during processing.
    """
    warnings: list[str] = []

    def log(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    # Step 1: extract rules from all procedures
    log("Extracting rules from procedures...")
    all_rules: list[DraftRule] = []
    for path_str in procedure_paths:
        path = Path(path_str)
        log(f"Reading: {path.name}")
        doc = read_procedure_file(path_str)
        for w in doc.warnings:
            warnings.append(w)
        rules = extract_rules_llm(doc.text, source_name=path.name, procedure_id=path.stem)
        prefix = path.stem[:8].upper().replace(" ", "_")
        for r in rules:
            r.rule_id = f"{prefix}_{r.rule_id}"
        log(f"  {len(rules)} rules from {path.name}")
        all_rules.extend(rules)

    # Step 2: read dataset
    log("Reading dataset...")
    headers, rows = read_excel_raw(dataset_path, max_rows=max_rows)
    log(f"  {len(rows)} rows, {len(headers)} columns")

    # Step 3: understand columns
    log("Mapping dataset columns (LLM)...")
    col_map = map_columns(headers, get_sample_rows(rows))
    audit_cols = [h for h in headers if col_map.get(h, {}).get("audit_relevant")]

    # Step 4+5: per row — match rules then audit
    row_results: list[RowAuditResult] = []
    for idx, row in enumerate(rows, start=1):
        row_id = next((v for v in list(row.values())[:3] if v), f"Row-{idx}")
        log(f"Auditing row {idx}/{len(rows)}: {row_id}")
        matched = match_rules_for_row(row, all_rules, col_map)
        finding = audit_row(row, matched, col_map)
        row_results.append(RowAuditResult(
            index=idx,
            row_id=row_id,
            row_data=row,
            matched=matched,
            finding=finding,
        ))

    return AuditResult(
        rules=all_rules,
        headers=headers,
        col_map=col_map,
        audit_cols=audit_cols,
        row_results=row_results,
        warnings=warnings,
    )
