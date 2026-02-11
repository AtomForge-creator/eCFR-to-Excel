from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple
import re


@dataclass
class ParseConfig:
    part_number: int = 63
    roman_lower_only: bool = True

    # How to join multiple lines that belong to the same paragraph:
    # "\n" preserves line breaks; " " makes one wrapped paragraph. Makes the out put readable
    join_lines_with: str = "\n"

    # Tokens treated as "reserved"
    reserved_tokens: tuple[str, ...] = ("[Reserved]", "[reserved]")

    # Regex strings (format with part number)
    section_regex: str = r"^\s*§\s*{part}\.(\d+)\s+(.*)$"

    # Marker token: supports "(i)" and "(i.)" at start-of-line
    # We will use a *multi-marker* peel approach, so this is the atomic marker pattern.
    marker_atom_regex: str = r"^\s*\(([^)]+)\)\.?\s*"

    # If True, we won't emit rows that have no Text (unless it's reserved).
    skip_empty_text_rows: bool = True

    def classify(self, tok: str) -> Tuple[Optional[str], Optional[int]]:
        """
        Returns (type, level) or (None, None) if token isn't recognized.
        Levels:
          1: letter  (a)
          2: number  (1)
          3: roman   (i)
          4: caps    (A)
        """
        tok = tok.strip()

        # (1)
        if re.fullmatch(r"[0-9]+", tok):
            return "number", 2

        # (i), (ii), (iv)...
        if self.roman_lower_only:
            if re.fullmatch(r"(?:i|ii|iii|iv|v|vi|vii|viii|ix|x|xi|xii|xiii|xiv|xv|xvi|xvii|xviii|xix|xx)", tok):
                return "roman", 3
        else:
            if re.fullmatch(r"(?:i|ii|iii|iv|v|vi|vii|viii|ix|x|xi|xii|xiii|xiv|xv|xvi|xvii|xviii|xix|xx)", tok):
                return "roman", 3

        # (A)
        if re.fullmatch(r"[A-Z]", tok):
            return "caps", 4

        # (a) excluding 'i' to avoid roman collision
        if re.fullmatch(r"[a-hj-z]", tok):
            return "letter", 1

        return None, None
    


