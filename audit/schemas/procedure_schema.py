from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProcedureDocument:
    file_path: str
    
    file_type: str
    text: str
    warnings: list[str] = field(default_factory=list)
    source: str = "pdf_text"
