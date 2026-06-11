"""
Generic audit runner — works with any procedure documents + any dataset.
No hardcoded column names, no domain-specific logic.

Usage:
  python -m audit.run_audit --excel <dataset.xlsx> <proc1.pdf> [proc2.pdf ...] [--rows N]

Pipeline:
  1. Read procedure PDFs  → LLM extracts rules
  2. Read Excel dataset   → LLM maps columns
  3. Per row              → LLM finds relevant rules + explains why
  (Step 4 = audit verdict pass/fail — next phase)
"""

from __future__ import annotations

import sys
from pathlib import Path

from audit.extractors import get_sheet_names, get_sample_rows, read_excel_raw, read_procedure_file
from audit.llm import extract_rules_llm, map_columns, match_rules_for_row
from audit.schemas.rule_schema import DraftRule

W = 80   # output width

def _sep(char="="):  print(char * W)
def _hdr(title):     print(f"\n{' ' + title + ' ':{'='}^{W}}")
def _row_sep():      print("-" * W)


def _collect_procedure_files(raw: list[str]) -> list[Path]:
    paths: list[Path] = []
    for r in raw:
        p = Path(r)
        if p.is_dir():
            paths.extend(sorted(p.glob("*.pdf")))
            paths.extend(sorted(p.glob("*.docx")))
        elif p.exists():
            paths.append(p)
        else:
            print(f"  WARN: not found — {r}")
    return paths


def _extract_all_rules(proc_paths: list[Path]) -> list[DraftRule]:
    all_rules: list[DraftRule] = []
    for path in proc_paths:
        print(f"  Reading : {path.name}")
        doc = read_procedure_file(str(path))
        for w in doc.warnings:
            print(f"  WARN    : {w}")
        rules = extract_rules_llm(
            doc.text,
            source_name=path.name,
            procedure_id=path.stem,
        )
        prefix = path.stem[:8].upper().replace(" ", "_")
        for r in rules:
            r.rule_id = f"{prefix}_{r.rule_id}"
        print(f"  Rules   : {len(rules)} extracted")
        all_rules.extend(rules)
    return all_rules


def _print_all_rules(rules: list[DraftRule]) -> None:
    _hdr(f" EXTRACTED RULES  ({len(rules)} total) ")
    print(f"  {'RULE ID':<20} {'TYPE':<12} {'PRIORITY':<10} {'TIMELINE':<10}")
    _sep("-")
    for r in rules:
        tl = f"{r.timeline_days}d" if r.timeline_days else "-"
        print(f"  {r.rule_id:<20} {r.rule_type:<12} {r.priority:<10} {tl:<10}")
        print(f"  Statement : {r.statement}")
        print(f"  Keywords  : {', '.join(r.keywords)}")
        _sep("-")


def _print_row(idx: int, row_id: str, audit_cols: list, row: dict,
               matched: list, col_map: dict) -> None:
    _hdr(f" ROW {idx}  |  {row_id} ")

    # Row field table
    print(f"  {'COLUMN':<38} {'VALUE'}")
    _sep("-")
    for h in audit_cols[:12]:
        val = row.get(h, "")
        if val:
            print(f"  {h:<38} {val}")
    _sep("-")

    print(f"\n  Relevant Rules Found : {len(matched)}\n")

    if not matched:
        print("  (no rules matched for this row)")
        return

    # Matched rules table
    print(f"  {'RULE ID':<22} {'PRIORITY':<10} {'TIMELINE':<10} WHY")
    _sep("-")
    for m in matched:
        tl = f"{m.rule.timeline_days}d" if m.rule.timeline_days else "-"
        print(f"  {m.rule.rule_id:<22} {m.priority:<10} {tl:<10} {m.relevance}")
        print(f"  {'':22} {'':10} {'':10} Rule: {m.rule.statement}")
        _sep("-")


def main() -> int:
    args = sys.argv[1:]

    max_rows = 5
    if "--rows" in args:
        i = args.index("--rows")
        max_rows = int(args[i + 1])
        args = args[:i] + args[i + 2:]

    if "--excel" not in args:
        print("Usage: python -m audit.run_audit --excel <dataset.xlsx> <proc.pdf> [--rows N]")
        return 1
    i = args.index("--excel")
    excel_path = args[i + 1]
    proc_raw   = args[:i] + args[i + 2:]

    if not proc_raw:
        print("Provide at least one procedure PDF after the --excel argument.")
        return 1

    # ── Step 1: Extract rules ─────────────────────────────────────────────
    _hdr(" STEP 1 : PROCEDURE RULE EXTRACTION ")
    proc_paths = _collect_procedure_files(proc_raw)
    if not proc_paths:
        print("No procedure files found.")
        return 1
    all_rules = _extract_all_rules(proc_paths)
    if not all_rules:
        print("No rules extracted — check if procedure text was readable.")
        return 1
    _print_all_rules(all_rules)

    # ── Step 2: Read dataset ──────────────────────────────────────────────
    _hdr(" STEP 2 : DATASET LOADING ")
    sheets = get_sheet_names(excel_path)
    print(f"  File    : {excel_path}")
    print(f"  Sheets  : {sheets}")
    headers, rows = read_excel_raw(excel_path, max_rows=max_rows)
    print(f"  Columns : {len(headers)}    Rows loaded : {len(rows)}")
    if not rows:
        print("No data rows found.")
        return 1

    # ── Step 3: Map columns ───────────────────────────────────────────────
    _hdr(" STEP 3 : COLUMN MAPPING (LLM) ")
    col_map = map_columns(headers, get_sample_rows(rows))
    audit_cols = [h for h in headers if col_map.get(h, {}).get("audit_relevant")]
    print(f"  {'COLUMN':<38} {'ROLE':<14} MEANING")
    _sep("-")
    for h in audit_cols:
        info = col_map.get(h, {})
        print(f"  {h:<38} {info.get('semantic_role',''):<14} {info.get('meaning','')}")
    _sep("-")

    # ── Step 4: Per-row rule matching ─────────────────────────────────────
    _hdr(" STEP 4 : RULE MATCHING PER ROW (LLM) ")

    for idx, row in enumerate(rows, start=1):
        row_id = next((v for v in list(row.values())[:3] if v), f"Row-{idx}")
        matched = match_rules_for_row(row, all_rules, col_map)
        _print_row(idx, row_id, audit_cols, row, matched, col_map)

    _sep("=")
    print(f"  COMPLETE  |  {len(rows)} rows  |  {len(all_rules)} rules  |  next: audit verdict")
    _sep("=")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
