"""
Extract audit rules from any procedure document using LLM.
No caching — rules are re-extracted on every run from the uploaded procedure text.
"""

from __future__ import annotations

import json

from audit.llm.client import chat
from audit.schemas.rule_schema import DraftRule

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


def extract_rules_llm(
    procedure_text: str,
    source_name: str = "procedure",
    procedure_id: str = "",
) -> list[DraftRule]:
    """Extract auditable rules from procedure text via LLM. No caching."""
    from pathlib import Path
    stem = procedure_id or Path(source_name).stem

    response = chat(
        [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": (
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

    rules = []
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
            procedure_id=stem,
            rule_type=str(r.get("rule_type", "mandatory")),
            priority=str(r.get("priority", "medium")),
            timeline_days=r.get("timeline_days"),
            keywords=[str(k).lower() for k in r.get("keywords", [])],
        ))

    print(f"    ({len(rules)} rules extracted from {source_name})")
    return rules
