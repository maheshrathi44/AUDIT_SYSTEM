"""
Past Observations — portable export of a completed audit's confirmed decisions.

Captures what a user confirmed on the Column Mapping, Rule Review, and Rule Check
Review pages so a future audit against a same-schema dataset (in a later session)
can pre-fill those decisions instead of re-asking the LLM and the user.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone

from audit.schemas.rule_schema import DraftRule

FORMAT_VERSION = 1

_REQUIRED_KEYS = {"col_map", "applicable_rules", "dropped_rules", "rule_checks"}


def build_past_observations(results, dataset_name: str) -> dict:
    """Serialize the confirmed decisions from a completed audit into a portable dict."""
    procedure_names = sorted({r.source_name for r in results.all_rules})
    return {
        "format_version":      FORMAT_VERSION,
        "generated_at":        datetime.now(timezone.utc).isoformat(),
        "source_dataset_name": dataset_name,
        "procedure_names":     procedure_names,
        "columns":             sorted(results.col_map.keys()),
        "col_map":             results.col_map,
        "applicable_rules":    [dataclasses.asdict(r) for r in results.applicable_rules],
        "dropped_rules":       results.dropped_rules,
        "rule_checks":         [dataclasses.asdict(c) for c in results.rule_checks],
        # Optional — absent in files saved before this existed, which is fine:
        # get_confidence_tally() below defaults to (0, 0) when a rule isn't present.
        "confidence_tally": {
            v.rule_id: {"confirm": v.confirm_count, "disagree": v.disagree_count}
            for v in results.verdicts
        },
    }


def dumps(results, dataset_name: str) -> str:
    return json.dumps(build_past_observations(results, dataset_name), indent=2)


def load(raw: str | bytes) -> dict | None:
    """Parse + validate a Past Observations file. Returns None if invalid/unsupported."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or data.get("format_version") != FORMAT_VERSION:
        return None
    if not _REQUIRED_KEYS.issubset(data.keys()):
        return None
    return data


# ── Partial-reuse matching — every function below returns (reused, remaining) ──
# so the caller only needs to send the "remaining" half to the LLM.

def split_columns(past: dict, headers: list[str]) -> tuple[dict, list[str]]:
    """Column mapping reuse — matched by exact column name."""
    saved_col_map = past.get("col_map", {})
    reused: dict = {}
    remaining: list[str] = []
    for h in headers:
        if h in saved_col_map:
            reused[h] = saved_col_map[h]
        else:
            remaining.append(h)
    return reused, remaining


def split_rules(
    past: dict, rules: list[DraftRule],
) -> tuple[list[DraftRule], dict[str, str], list[DraftRule]]:
    """
    Rule-filter reuse — matched by (rule_id, statement) for applicable rules
    (both must match, since a changed procedure sentence should be re-judged),
    or by rule_id alone for previously-dropped rules.
    Returns (reused_applicable, reused_dropped, remaining_rules_needing_llm_filter).
    """
    saved_applicable_keys = {
        (r.get("rule_id", ""), r.get("statement", "")) for r in past.get("applicable_rules", [])
    }
    saved_dropped = past.get("dropped_rules", {})

    reused_applicable: list[DraftRule] = []
    reused_dropped: dict[str, str] = {}
    remaining: list[DraftRule] = []

    for r in rules:
        if (r.rule_id, r.statement) in saved_applicable_keys:
            reused_applicable.append(r)
        elif r.rule_id in saved_dropped:
            reused_dropped[r.rule_id] = saved_dropped[r.rule_id]
        else:
            remaining.append(r)

    return reused_applicable, reused_dropped, remaining


def split_rule_checks(
    past: dict, applicable_rules: list[DraftRule],
) -> tuple[list[dict], list[DraftRule]]:
    """
    Rule-check reuse — matched by rule_id only (a rule check depends on the current
    dataset's columns, not the rule wording, so no statement match needed here).
    Returns (reused_check_dicts, remaining_rules_needing_llm_generation).
    """
    saved_checks_by_id = {c.get("rule_id", ""): c for c in past.get("rule_checks", [])}
    reused: list[dict] = []
    remaining: list[DraftRule] = []
    for r in applicable_rules:
        if r.rule_id in saved_checks_by_id:
            reused.append(saved_checks_by_id[r.rule_id])
        else:
            remaining.append(r)
    return reused, remaining


def get_user_added_rules(past: dict | None) -> list[DraftRule]:
    """
    Rules created via the '+ Add a new rule' UI have no procedure or report to be
    re-extracted from on a later audit, so they can't be picked up by split_rules
    like everything else — they must be reconstructed directly from what was saved.
    Only recovers ones that were applicable (dropped_rules only stores a reason
    string, not enough to rebuild a rule from scratch).
    """
    if not past:
        return []
    return [
        DraftRule(
            rule_id=r.get("rule_id", ""),
            section=r.get("section", "User Added"),
            source_section=r.get("source_section", "User Added"),
            statement=r.get("statement", ""),
            source_name="user-added",
            procedure_id=r.get("procedure_id", ""),
            rule_type=r.get("rule_type", "mandatory"),
            priority=r.get("priority", "medium"),
            timeline_days=r.get("timeline_days"),
            keywords=r.get("keywords", []) or [],
            is_manual=r.get("is_manual", False),
        )
        for r in past.get("applicable_rules", [])
        if r.get("source_name") == "user-added"
    ]


def get_confidence_tally(past: dict | None, rule_id: str) -> tuple[int, int] | None:
    """
    Saved (confirm, disagree) counts for a rule_id, carried over exactly as they
    were — no automatic adjustment just for being reused. Returns None if this
    rule has no saved tally yet (including for every file saved before this
    existed), so the caller falls back to a fresh seed instead.
    """
    if not past:
        return None
    entry = past.get("confidence_tally", {}).get(rule_id)
    if not entry:
        return None
    return int(entry.get("confirm", 0)), int(entry.get("disagree", 0))
