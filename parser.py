from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple
import re

from .config import ParseConfig
from .model import Row


class CFRParser:
    """
    Deterministic, line-based CFR parser.

    Supports multi-markers at the start of a line:
      (a)(1)(i)(A) Text...
      (a) (1) (i) (A) Text...

    Strategy:
      - Detect section headers and reset section context
      - Peel 0..N markers from the beginning of each line
      - If markers are found, finalize the prior paragraph (if any), update marker state, and start a new paragraph buffer
      - Otherwise treat as continuation line for the current paragraph
    """
    #FIX THIS; NEEDS EXCEPTION HANDLING FOR DIFFERENT REGULATION BUILDS; NEEDS TO RETURN /N OR NONE TO HANDLE EXCEPTION CASES   
    def __init__(self, cfg: ParseConfig):
        self.cfg = cfg
        self.section_re = re.compile(cfg.section_regex.format(part=cfg.part_number))
        self.marker_atom_re = re.compile(cfg.marker_atom_regex)

        # State
        self.section_num: Optional[str] = None
        self.title: Optional[str] = None

        self.letter: Optional[str] = None
        self.number: Optional[str] = None
        self.roman: Optional[str] = None
        self.caps: Optional[str] = None

        self.text_buf: List[str] = []

    def _current_path(self) -> Optional[str]:
        if self.section_num is None:
            return None
        path = f"§{self.cfg.part_number}.{self.section_num}"
        if self.letter:
            path += f"({self.letter})"
        if self.number:
            path += f"({self.number})"
        if self.roman:
            path += f"({self.roman})"
        if self.caps:
            path += f"({self.caps})"
        return path

    def _buf_text(self) -> str:
        # Preserve verbatim-ish: strip only trailing whitespace per line
        joined = self.cfg.join_lines_with.join([t.rstrip() for t in self.text_buf]).strip()
        return joined

    def _is_reserved(self, txt: str) -> bool:
        t = txt.strip()
        return t in self.cfg.reserved_tokens

    def _has_any_content(self) -> bool:
        # content exists if we have markers set OR text buffer has non-whitespace
        if any([self.letter, self.number, self.roman, self.caps]):
            return True
        return len(self._buf_text().strip()) > 0

    def _finalize(self, rows: List[Row]) -> None:
        """
        Emit the current paragraph row (if valid), then clear the text buffer.
        Does not clear markers; markers represent the current paragraph identity. Runs into trouble with recognizing
        new paragraphs after certian section header cases
        """
        if self.section_num is None:
            self.text_buf = []
            return

        path = self._current_path()
        if path is None:
            self.text_buf = []
            return

        txt = self._buf_text()

        # Skip empty text rows unless reserved or config says to keep them
        if self.cfg.skip_empty_text_rows and (txt.strip() == "") and (not self._is_reserved(txt)):
            self.text_buf = []
            return

        num_val: Optional[int] = None
        if self.number and self.number.isdigit():
            num_val = int(self.number)

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

        self.text_buf = []

    def _set_level(self, level: int, tok: str) -> None:
        """
        Set the appropriate marker level and clear deeper levels.
        Keeps parent levels intact.
        """
        if level == 1:
            self.letter = tok
            self.number = None
            self.roman = None
            self.caps = None
        elif level == 2:
            self.number = tok
            self.roman = None
            self.caps = None
        elif level == 3:
            self.roman = tok
            self.caps = None
        elif level == 4:
            self.caps = tok

    def _peel_markers(self, line: str) -> Tuple[List[Tuple[str, int]], str]:
        """
        Peel consecutive markers from the start of the line.
        Returns (markers, remainder_text).

        markers: list of (token, level) in the order encountered.
        remainder_text: whatever remains after removing leading markers/spaces.
        """
        markers: List[Tuple[str, int]] = []
        s = line

        while True:
            m = self.marker_atom_re.match(s)
            if not m:
                break

            tok = m.group(1).strip()
            typ, level = self.cfg.classify(tok)
            if typ is None or level is None:
                # Not a valid marker token; stop peeling and treat the line as content.
                break

            markers.append((tok, level))
            s = s[m.end() :]  # remove the matched marker and any trailing spaces after it

        return markers, s

    def parse_lines(self, lines: List[str]) -> List[Row]:
        rows: List[Row] = []

        for raw in lines:
            ln = raw.rstrip("\n")

            # Section header?
            m_sec = self.section_re.match(ln)
            if m_sec:
                # finalize any trailing paragraph for prior section
                if self._has_any_content():
                    self._finalize(rows)

                # start new section context
                self.section_num = m_sec.group(1).strip()
                self.title = m_sec.group(2).strip()

                # reset markers and buffer
                self.letter = self.number = self.roman = self.caps = None
                self.text_buf = []
                continue

            # Ignore content before first section
            if self.section_num is None:
                continue

            # Peel markers (possibly multiple)
            markers, remainder = self._peel_markers(ln)

            if markers:
                # If we were building a previous paragraph, finalize it first
                if self._has_any_content():
                    self._finalize(rows)

                # Apply markers in order
                for tok, level in markers:
                    self._set_level(level, tok)

                remainder = remainder.strip()
                self.text_buf = [remainder] if remainder else []
                continue

            # Continuation line (including indented lines)
            # Preserve text; strip only leading/trailing whitespace to avoid runaway indentation,
            # but keep line breaks via join_lines_with.
            self.text_buf.append(ln.strip())

        # finalize trailing paragraph at EOF
        if self._has_any_content():
            self._finalize(rows)

        return rows
