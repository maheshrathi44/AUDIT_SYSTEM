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

from audit.extractors import get_sheet_names, read_excel_raw, read_procedure_file
from audit.llm import extract_rules_llm, map_columns, match_rules_for_row
from audit.schemas.rule_schema import DraftRule

PRIORITY_TAG = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}


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
        print(f"  Reading: {path.name}")
        doc = read_procedure_file(str(path))
        for w in doc.warnings:
            print(f"    WARN: {w}")
        rules = extract_rules_llm(
            doc.text,
            source_name=path.name,
            procedure_id=path.stem,
        )
        prefix = path.stem[:8].upper().replace(" ", "_")
        for r in rules:
            r.rule_id = f"{prefix}_{r.rule_id}"
        print(f"    → {len(rules)} rules extracted")
        all_rules.extend(rules)
    return all_rules


def _print_all_rules(rules: list[DraftRule]) -> None:
    print(f"\n{'='*70}")
    print(f"  EXTRACTED RULES ({len(rules)} total)")
    print(f"{'='*70}")
    for r in rules:
        tl = f"  [limit: {r.timeline_days}d]" if r.timeline_days else ""
        print(f"  [{r.rule_id}]  {r.rule_type:<10}  {r.priority:<8}{tl}")
        print(f"    {r.statement}")
        print(f"    keywords: {', '.join(r.keywords)}")
        print()


def main() -> int:
    args = sys.argv[1:]

    # parse --rows
    max_rows = 5
    if "--rows" in args:
        i = args.index("--rows")
        max_rows = int(args[i + 1])
        args = args[:i] + args[i + 2:]

    # parse --excel
    if "--excel" not in args:
        print("Usage: python -m audit.run_audit --excel <dataset.xlsx> <proc.pdf> [--rows N]")
        return 1
    i = args.index("--excel")
    excel_path = args[i + 1]
    proc_raw   = args[:i] + args[i + 2:]

    if not proc_raw:
        print("Provide at least one procedure PDF after the --excel argument.")
        return 1

    # ── Step 1: Extract rules from procedures ─────────────────────────────
    print("\n[1] Extracting rules from procedures via LLM ...")
    proc_paths = _collect_procedure_files(proc_raw)
    if not proc_paths:
        print("No procedure files found.")
        return 1

    all_rules = _extract_all_rules(proc_paths)
    if not all_rules:
        print("No rules extracted — check if procedure text was readable.")
        return 1
    _print_all_rules(all_rules)

    # ── Step 2: Read dataset ───────────────────────────────────────────────
    print(f"\n[2] Reading dataset: {excel_path}")
    sheets = get_sheet_names(excel_path)
    print(f"    Sheets: {sheets}")
    headers, rows = read_excel_raw(excel_path, max_rows=max_rows)
    print(f"    Columns: {len(headers)}   Rows loaded: {len(rows)}")

    if not rows:
        print("No data rows found in dataset.")
        return 1

    # ── Step 3: Map columns ────────────────────────────────────────────────
    print("\n[3] Understanding dataset columns via LLM ...")
    col_map = map_columns(headers, rows[0])
    audit_cols = [h for h in headers if col_map.get(h, {}).get("audit_relevant")]
    print(f"    Audit-relevant columns ({len(audit_cols)}):")
    for h in audit_cols:
        info = col_map.get(h, {})
        print(f"      {h:<40} {info.get('semantic_role',''):<12}  {info.get('meaning','')}")

    # ── Step 4: Match rules per row ────────────────────────────────────────
    print(f"\n[4] Matching relevant rules to each row via LLM ...")

    for idx, row in enumerate(rows, start=1):
        row_id = next((v for v in list(row.values())[:3] if v), f"Row-{idx}")

        print(f"\n{'─'*70}")
        print(f"  Row {idx}: {row_id}")

        # print audit-relevant fields for this row
        for h in audit_cols[:10]:
            val = row.get(h, "")
            if val:
                print(f"    {h}: {val}")

        matched = match_rules_for_row(row, all_rules, col_map)
        print(f"\n  Relevant rules → {len(matched)}")

        if not matched:
            print("    (none matched)")
            continue

        for m in matched:
            tag = PRIORITY_TAG.get(m.priority, "⚪")
            tl  = f"  [limit: {m.rule.timeline_days}d]" if m.rule.timeline_days else ""
            print(f"\n  {tag} [{m.rule.rule_id}]  {m.priority}{tl}")
            print(f"     Rule : {m.rule.statement}")
            print(f"     Why  : {m.relevance}")

    print(f"\n{'='*70}")
    print(f"Done — {len(rows)} rows processed  |  {len(all_rules)} rules  |  audit verdict: next step")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
