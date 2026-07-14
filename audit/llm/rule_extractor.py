"""
Extract audit rules from any procedure document using LLM.
Cache: SHA256 of procedure text content → .audit_cache/rules_<hash>.json
Same file uploaded again → instant cache hit, zero LLM call.
Remove the cache dir to force re-extraction.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from audit.llm.client import chat
from audit.schemas.rule_schema import DraftRule

_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / ".audit_cache"

_SYSTEM = """\
You are an audit rule extractor. Your job is to read a procedure document and extract meaningful, auditable rules from it.

CORE PRINCIPLE — judge every sentence by its CONTENT, not by which section it appears in:

  EXTRACT if the sentence (alone or combined with nearby sentences) says:
    - someone MUST do something
    - something MUST happen within a time limit ("within 30 days...")
    - a condition that triggers an action ("if part not available, then...")
    - an approval or sign-off requirement ("approved by...")
    - a check or verification step ("effectiveness to be confirmed...")

  MERGE nearby sentences into ONE rule if they together describe a single step or obligation.

  SKIP only pure descriptions with zero obligation:
    - A sentence that only defines what a word means with no action attached
    - A sentence that only states the document's purpose with no obligation
    - Judge this by content, NOT by the heading above it

Return ONLY valid JSON:
{
  "rules": [
    {
      "rule_id": "R01",
      "section": "name of the section this came from",
      "statement": "complete self-contained obligation in one clear sentence",
      "rule_type": "timeline",
      "priority": "high",
      "timeline_days": 30,
      "keywords": ["4", "to", "8", "key", "terms"]
    }
  ]
}

Field rules:
- rule_id: sequential (R01, R02, ...)
- section: use whatever section name the document itself uses — do not normalise or rename it
- statement: the full obligation, self-contained and auditable as a standalone sentence
- rule_type: timeline | mandatory | approval | advisory
- priority: critical | high | medium | low
- timeline_days: integer days if a time limit exists (1 month=30, 2 months=60), else null
- keywords: 4-8 lowercase terms that would help match this rule to a data row"""


def _content_hash(text: str) -> str:
    return hashlib.sha256(text[:50_000].encode()).hexdigest()[:16]


def extract_rules_llm(
    procedure_text: str,
    source_name: str = "procedure",
    procedure_id: str = "",
    system_prompt: str | None = None,
    is_manual: bool = False,
) -> list[DraftRule]:
    """
    Extract auditable rules from procedure text.
    Cache key = SHA256 of content (+ manual/procedure kind) — same file, any
    filename → instant hit. Delete .audit_cache/ to force fresh extraction.

    system_prompt / is_manual: used by manual_report_extractor.py to reuse this
    same caching + parsing machinery with a differently-worded prompt for a past
    human-written audit report instead of a procedure. Every existing caller
    omits both, so existing behavior is unchanged.
    """
    from pathlib import Path as _Path
    stem = procedure_id or _Path(source_name).stem
    prompt = system_prompt or _SYSTEM

    # ── cache lookup ───────────────────────────────────────────────────────────
    _CACHE_DIR.mkdir(exist_ok=True)
    kind = "manual_" if is_manual else ""
    cache_file = _CACHE_DIR / f"rules_{kind}{_content_hash(procedure_text)}.json"

    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text())
            rules = _parse_rules(data.get("rules", []), source_name, stem, is_manual=is_manual)
            if rules:
                print(f"    (cache hit — {len(rules)} rules, skipping LLM for {source_name})")
                return rules
        except Exception:
            pass

    # ── LLM extraction ─────────────────────────────────────────────────────────
    response = chat(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": (
                "Extract all auditable rules from this document:\n\n"
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

    rules = _parse_rules(data.get("rules", []), source_name, stem, is_manual=is_manual)

    # save to cache
    cache_file.write_text(json.dumps({"source_name": source_name, "rules": data.get("rules", [])}, indent=2))
    print(f"    ({len(rules)} rules extracted and cached for {source_name})")
    return rules


def _parse_rules(raw: list[dict], source_name: str, stem: str, is_manual: bool = False) -> list[DraftRule]:
    rules = []
    for i, r in enumerate(raw, start=1):
        stmt = str(r.get("statement", "")).strip()
        if not stmt:
            continue
        rules.append(DraftRule(
            rule_id=str(r.get("rule_id", f"R{i:02d}")),
            section=str(r.get("section", "general")),
            source_section=str(r.get("section", "general")),
            statement=stmt,
            source_name=source_name,
            procedure_id=stem,
            rule_type=str(r.get("rule_type", "mandatory")),
            priority=str(r.get("priority", "medium")),
            timeline_days=r.get("timeline_days"),
            keywords=[str(k).lower() for k in r.get("keywords", [])],
            is_manual=is_manual,
        ))
    return rules
