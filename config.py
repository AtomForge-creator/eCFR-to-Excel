from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Literal, TypeAlias
import re


# ============================
# CHANGE: Added clear type aliases so return types are easier to read.
# ============================
MarkerType: TypeAlias = Literal["letter", "number", "roman", "caps"]
Classification: TypeAlias = tuple[Optional[MarkerType], Optional[int]]


# ============================
# CHANGE: Replaced magic numbers with named constants.
# ============================
LEVEL_LETTER = 1
LEVEL_NUMBER = 2
LEVEL_ROMAN = 3
LEVEL_CAPS = 4


# ============================
# CHANGE: Pulled regex patterns into module-level constants.
# ============================
ROMAN_PATTERN = r"(?:i|ii|iii|iv|v|vi|vii|viii|ix|x|xi|xii|xiii|xiv|xv|xvi|xvii|xviii|xix|xx)"


# ============================
# CHANGE: Precompiled commonly used regexes for efficiency and readability.
# ============================
NUMBER_RE = re.compile(r"[0-9]+")
CAPS_RE = re.compile(r"[A-Z]")
LOWER_LETTER_RE = re.compile(r"[a-z]")   # includes 'i' on purpose; parser resolves ambiguity
ROMAN_RE = re.compile(ROMAN_PATTERN)


@dataclass
class ParseConfig:
    part_number: int = 63

    # How to join multiple lines that belong to the same paragraph:
    # "\n" preserves line breaks; " " makes one wrapped paragraph.
    join_lines_with: str = "\n"

    # ============================
    # CHANGE: Keep reserved tokens canonicalized to lowercase.
    # ============================
    reserved_tokens: tuple[str, ...] = ("[reserved]",)

    # Regex strings (format with part number)
    section_regex: str = r"^\s*§\s*{part}\.(\d+)\s+(.*)$"

    # Marker token: supports "(i)" and "(i.)" at start-of-line
    marker_atom_regex: str = r"^\s*\(([^)]+)\)\.?\s*"

    # If True, we won't emit rows that have no Text (unless it's reserved).
    skip_empty_text_rows: bool = True

    def get_section_re(self) -> re.Pattern[str]:
        # CHANGE: Escaped part number for safer interpolation.
        return re.compile(self.section_regex.format(part=re.escape(str(self.part_number))))

    def get_marker_atom_re(self) -> re.Pattern[str]:
        return re.compile(self.marker_atom_regex)

    def is_reserved_token(self, text: str) -> bool:
        return text.strip().lower() in self.reserved_tokens

    # ============================
    # CHANGE: Added a candidate classifier instead of forcing one answer too early.
    # This is the important fix for ambiguous tokens like lowercase 'i',
    # which can be either:
    #   - letter level: (i)
    #   - roman level:  (i)
    # The parser will decide using context.
    # ============================
    def classify_candidates(self, tok: str) -> list[tuple[MarkerType, int]]:
        tok = tok.strip()
        out: list[tuple[MarkerType, int]] = []

        if NUMBER_RE.fullmatch(tok):
            out.append(("number", LEVEL_NUMBER))

        if CAPS_RE.fullmatch(tok):
            out.append(("caps", LEVEL_CAPS))

        if ROMAN_RE.fullmatch(tok):
            out.append(("roman", LEVEL_ROMAN))

        if LOWER_LETTER_RE.fullmatch(tok):
            out.append(("letter", LEVEL_LETTER))

        return out

    # ============================
    # CHANGE: classify() now only returns a result for unambiguous tokens.
    # Ambiguous ones like 'i' return (None, None) so the parser can resolve them.
    # ============================
    def classify(self, tok: str) -> Classification:
        candidates = self.classify_candidates(tok)
        if len(candidates) == 1:
            return candidates[0]
        return None, None