"""
Extract audit rules from a PAST HUMAN-WRITTEN audit report — not a procedure.

Reuses rule_extractor.extract_rules_llm's caching + parsing machinery with a
differently-worded prompt: a procedure describes obligations that MUST happen,
a manual audit report describes checks a human already performed and their
results. Rules extracted here are tagged is_manual=True, which seeds them at
High confidence (see audit/confidence.py) — a human auditor already validated
this finding in a real completed audit.
"""

from __future__ import annotations

from audit.llm.rule_extractor import extract_rules_llm
from audit.schemas.rule_schema import DraftRule

_MANUAL_SYSTEM = """\
You are an audit analyst reading a COMPLETED audit report — not a procedure.
This document describes checks a human auditor already performed and what they
found, not obligations that must happen going forward.

CORE PRINCIPLE — judge every sentence by its CONTENT:

  EXTRACT if the sentence (alone or combined with nearby sentences) describes:
    - a specific check or criterion the auditor evaluated
    - a finding, observation, or instance of non-compliance the auditor reported
    - a risk rating or classification (High/Medium/Low, DD/OI/LC/SL) tied to a finding

  Rephrase each finding as a general, self-contained AUDITABLE RULE STATEMENT —
  the underlying criterion being checked, not the one-time result. For example,
  a finding like "18 of 31 FTIRs were closed citing 'Failed Part Not Available'
  without a countermeasure" should become a rule like "FTIR closure must not cite
  'Failed Part Not Available' without an accompanying countermeasure."

  SKIP purely descriptive text with no auditable criterion — scope statements,
  section headers, sign-off blocks, page numbers.

Return ONLY valid JSON, same shape every time:
{
  "rules": [
    {
      "rule_id": "R01",
      "section": "name of the section this came from",
      "statement": "the underlying criterion, as a complete self-contained auditable rule",
      "rule_type": "timeline",
      "priority": "high",
      "timeline_days": 30,
      "keywords": ["4", "to", "8", "key", "terms"]
    }
  ]
}

Field rules:
- rule_id: sequential (R01, R02, ...)
- section: use whatever section/heading name the report itself uses
- statement: the general auditable criterion, self-contained and standalone
- rule_type: timeline | mandatory | approval | advisory
- priority: critical | high | medium | low — use the report's own risk rating if it states one
- timeline_days: integer days if a time limit is implied, else null
- keywords: 4-8 lowercase terms that would help match this rule to a data row"""


def extract_manual_findings_llm(
    report_text: str,
    source_name: str = "manual_report",
    procedure_id: str = "",
) -> list[DraftRule]:
    """Extract auditable rules from a past human-written audit report. Cached like extract_rules_llm."""
    return extract_rules_llm(
        report_text,
        source_name=source_name,
        procedure_id=procedure_id,
        system_prompt=_MANUAL_SYSTEM,
        is_manual=True,
    )
