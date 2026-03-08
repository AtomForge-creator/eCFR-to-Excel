from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

from config import (
    ParseConfig,
    LEVEL_LETTER,
    LEVEL_NUMBER,
    LEVEL_ROMAN,
    LEVEL_CAPS,
)
from model import Row


class CFRParser:
    """
    Deterministic, line-based CFR parser.

    Supports multi-markers at the start of a line:
      (a)(1)(i)(A) Text...
      (a) (1) (i) (A) Text...

    Strategy:
      - Detect section headers and reset section context
      - Peel 0..N markers from the beginning of each line
      - If markers are found, finalize the prior paragraph (if any), update marker state,
        and start a new paragraph buffer
      - Otherwise treat as continuation line for the current paragraph
    """

    def __init__(self, cfg: ParseConfig):
        self.cfg = cfg

        # CHANGE: Use config helper methods instead of recompiling regexes manually.
        self.section_re = cfg.get_section_re()
        self.marker_atom_re = cfg.get_marker_atom_re()

        # CHANGE: Added warnings collection so weird input can be diagnosed later.
        self.warnings: List[str] = []

        # CHANGE: Centralized parser state reset into a helper.
        self.reset()

    def reset(self) -> None:
        # CHANGE: Added explicit reset helper so parser state does not leak between runs.
        self.section_num: Optional[str] = None
        self.title: Optional[str] = None
        self._reset_markers()
        self.text_buf: List[str] = []

    def _reset_markers(self) -> None:
        # CHANGE: Added marker reset helper to avoid repeating reset logic.
        self.letter: Optional[str] = None
        self.number: Optional[str] = None
        self.roman: Optional[str] = None
        self.caps: Optional[str] = None

    def _current_path(self) -> Optional[str]:
        if self.section_num is None:
            return None

        path = f"§{self.cfg.part_number}.{self.section_num}"

        # CHANGE: Reduced repetitive path-building code.
        for tok in (self.letter, self.number, self.roman, self.caps):
            if tok:
                path += f"({tok})"

        return path

    def _buf_text(self) -> str:
        # Preserve verbatim-ish: strip only trailing whitespace per line.
        return self.cfg.join_lines_with.join(t.rstrip() for t in self.text_buf).strip()

    def _is_reserved(self, txt: str) -> bool:
        # CHANGE: Use config helper for case-insensitive reserved-token handling.
        return self.cfg.is_reserved_token(txt)

    def _has_text_content(self) -> bool:
        # CHANGE: Avoid rebuilding the full joined buffer just to check for content.
        return any(t.strip() for t in self.text_buf)

    def _has_marker_state(self) -> bool:
        return any((self.letter, self.number, self.roman, self.caps))

    def _has_open_paragraph_state(self) -> bool:
        # CHANGE: Clearer split between marker state and actual text content.
        return self._has_marker_state() or self._has_text_content()

    def _warn(self, message: str) -> None:
        self.warnings.append(message)

    # ============================
    # CHANGE: Added context-aware classification.
    # This is the real fix for ambiguous '(i)'.
    #
    # Why:
    #   - 'i' can be a top-level letter marker
    #   - 'i' can also be a roman marker under a number marker
    #
    # Strategy:
    #   1. Ask config for all valid candidate interpretations
    #   2. If only one, use it
    #   3. If ambiguous, resolve using marker-chain context and parser state
    # ============================
    def _classify_with_context(self, tok: str, prev_level: int = 0) -> Tuple[Optional[str], Optional[int]]:
        candidates = self.cfg.classify_candidates(tok)

        if not candidates:
            return None, None

        if len(candidates) == 1:
            return candidates[0]

        candidate_map = {typ: level for typ, level in candidates}

        # CHANGE: If the previous marker in the same chain was a number,
        # '(i)' is very likely roman, as in (3)(i).
        if prev_level == LEVEL_NUMBER and "roman" in candidate_map:
            return "roman", candidate_map["roman"]

        # CHANGE: If the previous marker in the same chain was a letter,
        # a following '(i)' is more likely a number/roman child than a new letter.
        if prev_level == LEVEL_LETTER and "roman" in candidate_map:
            return "roman", candidate_map["roman"]

        # CHANGE: If we are already under an active number marker from current state,
        # prefer roman.
        if self.number is not None and "roman" in candidate_map:
            return "roman", candidate_map["roman"]

        # CHANGE: If starting fresh on a line and token is ambiguous, prefer letter.
        # This helps cases where '(i)' is actually a sibling letter paragraph.
        if prev_level == 0 and "letter" in candidate_map:
            return "letter", candidate_map["letter"]

        # CHANGE: Default fallback for ambiguous lowercase single letters.
        if "letter" in candidate_map:
            return "letter", candidate_map["letter"]

        return candidates[0]

    def _finalize(self, rows: List[Row]) -> None:
        """
        Emit the current paragraph row (if valid), then clear the text buffer.
        Does not clear markers; markers represent the current paragraph identity.
        """
        if self.section_num is None:
            self.text_buf = []
            return

        path = self._current_path()
        if path is None:
            self.text_buf = []
            return

        txt = self._buf_text()

        is_empty = txt.strip() == ""
        is_reserved = self._is_reserved(txt)

        # CHANGE: Made skip logic easier to read.
        if self.cfg.skip_empty_text_rows and is_empty and not is_reserved:
            self.text_buf = []
            return

        num_val: Optional[int] = None
        if self.number and self.number.isdigit():
            num_val = int(self.number)

        # CHANGE: Wrapped Row creation in a more useful error message.
        try:
            rows.append(
                Row(
                    Section=f"{self.cfg.part_number}.{self.section_num}",
                    Title=(self.title or "").strip(),
                    Letter=self.letter,
                    Number=num_val,
                    Roman=self.roman,
                    Caps=self.caps,
                    Path=path,
                    Text=txt,
                )
            )
        except Exception as e:
            raise ValueError(
                f"Failed to build row for section={self.section_num!r}, path={path!r}"
            ) from e

        self.text_buf = []

    def _set_level(self, level: int, tok: str) -> None:
        """
        Set the appropriate marker level and clear deeper levels.
        Keeps parent levels intact.
        """
        if level == LEVEL_LETTER:
            self.letter = tok
            self.number = None
            self.roman = None
            self.caps = None
        elif level == LEVEL_NUMBER:
            self.number = tok
            self.roman = None
            self.caps = None
        elif level == LEVEL_ROMAN:
            self.roman = tok
            self.caps = None
        elif level == LEVEL_CAPS:
            self.caps = tok
        else:
            raise ValueError(f"Unsupported marker level: {level}")

    def _peel_markers(self, line: str) -> Tuple[List[Tuple[str, int]], str]:
        """
        Peel consecutive markers from the start of the line.
        Returns (markers, remainder_text).

        markers: list of (token, level) in the order encountered.
        remainder_text: whatever remains after removing leading markers/spaces.
        """
        markers: List[Tuple[str, int]] = []
        s = line
        prev_level = 0

        while True:
            m = self.marker_atom_re.match(s)
            if not m:
                break

            tok = m.group(1).strip()

            # CHANGE: Replaced config.classify() with context-aware parser classification.
            typ, level = self._classify_with_context(tok, prev_level)

            if typ is None or level is None:
                # Not a valid marker token; stop peeling and treat the line as content.
                break

            # CHANGE: Added warning for suspicious marker-order transitions.
            if prev_level and level < prev_level and level != LEVEL_LETTER:
                self._warn(
                    f"Suspicious marker order in section {self.section_num or '?'}: "
                    f"{[t for t, _ in markers]} -> {tok}"
                )

            markers.append((tok, level))
            prev_level = level
            s = s[m.end():]

        return markers, s

    def parse_lines(self, lines: Iterable[str]) -> List[Row]:
        # CHANGE: Reset parser state at the start of each run.
        self.reset()
        self.warnings = []

        rows: List[Row] = []

        for line_no, raw in enumerate(lines, start=1):
            ln = raw.rstrip("\n")

            # Section header?
            m_sec = self.section_re.match(ln)
            if m_sec:
                if self._has_open_paragraph_state():
                    self._finalize(rows)

                self.section_num = m_sec.group(1).strip()
                self.title = m_sec.group(2).strip()

                self._reset_markers()
                self.text_buf = []
                continue

            # Ignore content before first section, but record it if non-blank.
            if self.section_num is None:
                if ln.strip():
                    self._warn(f"Ignored content before first section at line {line_no}: {ln[:120]!r}")
                continue

            markers, remainder = self._peel_markers(ln)

            if markers:
                if self._has_open_paragraph_state():
                    self._finalize(rows)

                for tok, level in markers:
                    self._set_level(level, tok)

                remainder = remainder.strip()
                self.text_buf = [remainder] if remainder else []
                continue

            # CHANGE: Skip blank continuation lines instead of adding empty junk.
            clean = ln.strip()
            if clean:
                self.text_buf.append(clean)

        if self._has_open_paragraph_state():
            self._finalize(rows)

        return rows