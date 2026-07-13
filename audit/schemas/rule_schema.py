from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DraftRule:
    rule_id: str
    section: str
    source_section: str
    statement: str
    source_name: str
    procedure_id: str = ""  # e.g. MQ/01, MQ/07, MQ/15

    rule_type: str = "mandatory"
    priority: str = "medium"
    timeline_days: int | None = None

    keywords: list[str] = field(default_factory=list)

    # True only for a rule extracted from a past human-written audit report
    # (not a procedure). Defaults False for every existing rule source.
    is_manual: bool = False