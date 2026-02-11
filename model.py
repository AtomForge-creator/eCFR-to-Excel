from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

#FIX THIS; DOES NOT WORK ACROSS DIFFERENT REGS
@dataclass
class Row:
    Section: str
    Title: str
    Letter: Optional[str]
    Number: Optional[int]
    Roman: Optional[str]
    Caps: Optional[str]
    Path: str
    Text: str
