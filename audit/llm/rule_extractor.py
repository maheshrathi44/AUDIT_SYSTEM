"""
Extract audit rules from any procedure document using LLM.
Rules are cached to .audit_cache/<stem>.json so LLM is not called again on re-runs.
"""

from __future__ import annotations

import json
from pathlib import Path

from audit.llm.client import chat, get_model
from audit.schemas.rule_schema import DraftRule

_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / ".audit_cache"

_SYSTEM = """\
You are an audit rule extractor. Read the procedure document text and extract EVERY auditable rule, requirement, or obligation.

Return ONLY valid JSON in this exact format:
{
  "rules": [
    {
      "rule_id": "R01",
      "section": "methodology",
      "statement": "exact or paraphrased rule from the document",
      "rule_type": "timeline",
      "priority": "high",
      "timeline_days": 30,
      "keywords": ["attribution", "reply", "30", "days"]
    }
  ]
}

Field rules:
- rule_id: sequential (R01, R02, ...)
- section: which part of the document (objective/scope/methodology/timelines/criteria/action/monitoring/general)
- statement: the full requirement in one clear sentence
- rule_type: timeline | mandatory | approval | advisory
  timeline  = has a specific time limit (e.g. "within 30 days", "1 month")
  mandatory = must always be done, no time limit
  approval  = requires sign-off, escalation, or committee decision
  advisory  = recommended practice, not strictly enforced
- priority: critical | high | medium | low
- timeline_days: integer days if rule has a time limit (1 month=30, 2 months=60), else null
- keywords: 4-8 key terms useful for matching this rule to case data (lowercase)

Extract EVERY distinct requirement. Do not skip anything. Do not merge separate requirements."""


def _cache_path(procedure_id: str) -> Path:
    _CACHE_DIR.mkdir(exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in procedure_id)
    return _CACHE_DIR / f"{safe}.json"


def _save_cache(procedure_id: str, rules: list[DraftRule], model: str) -> None:
    data = {
        "procedure_id": procedure_id,
        "model": model,
        "rules": [
            {
                "rule_id":      r.rule_id,
                "section":      r.section,
                "source_section": r.source_section,
                "statement":    r.statement,
                "source_name":  r.source_name,
                "procedure_id": r.procedure_id,
                "rule_type":    r.rule_type,
                "priority":     r.priority,
                "timeline_days": r.timeline_days,
                "keywords":     r.keywords,
            }
            for r in rules
        ],
    }
    _cache_path(procedure_id).write_text(json.dumps(data, indent=2))


def _load_cache(procedure_id: str) -> list[DraftRule] | None:
    p = _cache_path(procedure_id)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        return [
            DraftRule(
                rule_id=r["rule_id"],
                section=r["section"],
                source_section=r["source_section"],
                statement=r["statement"],
                source_name=r["source_name"],
                procedure_id=r["procedure_id"],
                rule_type=r["rule_type"],
                priority=r["priority"],
                timeline_days=r.get("timeline_days"),
                keywords=r.get("keywords", []),
            )
            for r in data.get("rules", [])
        ]
    except Exception:
        return None


def extract_rules_llm(
    procedure_text: str,
    source_name: str = "procedure",
    procedure_id: str = "",
    force_refresh: bool = False,
) -> list[DraftRule]:
    """
    Extract rules from procedure text using LLM.
    Cached: if same procedure was processed before, loads from .audit_cache/.
    Pass force_refresh=True to re-extract even if cache exists.
    """
    cache_key = procedure_id or source_name

    if not force_refresh:
        cached = _load_cache(cache_key)
        if cached:
            print(f"    (loaded {len(cached)} rules from cache — skipping LLM call)")
            return cached

    response = chat(
        [
            {"role": "system", "content": _SYSTEM},
            {"role": "user",   "content": (
                "Extract all auditable rules from this procedure document:\n\n"
                + procedure_text[:12000]
            )},
        ],
        json_mode=True,
    )

    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        print(f"  WARN: LLM returned invalid JSON for {source_name}")
        return []

    rules: list[DraftRule] = []
    for i, r in enumerate(data.get("rules", []), start=1):
        stmt = str(r.get("statement", "")).strip()
        if not stmt:
            continue
        rules.append(DraftRule(
            rule_id=str(r.get("rule_id", f"R{i:02d}")),
            section=str(r.get("section", "general")),
            source_section=str(r.get("section", "general")),
            statement=stmt,
            source_name=source_name,
            procedure_id=procedure_id,
            rule_type=str(r.get("rule_type", "mandatory")),
            priority=str(r.get("priority", "medium")),
            timeline_days=r.get("timeline_days"),
            keywords=[str(k).lower() for k in r.get("keywords", [])],
        ))

    _save_cache(cache_key, rules, get_model())
    print(f"    (rules saved to cache for next run)")
    return rules
