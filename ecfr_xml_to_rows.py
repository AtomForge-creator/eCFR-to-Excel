from __future__ import annotations

from dataclasses import asdict
from typing import Iterable, List, Optional
from urllib.parse import urlencode
import csv
import re
import time
import xml.etree.ElementTree as ET

import requests

from model import Row


# ============================================================
# CONFIG
# ============================================================
DATE = "2024-01-01"
TITLE = 40
PART = "63"
SUBPART = "H"        # CHANGE: whole Subpart H
SECTION = None       # CHANGE: set to a value like "63.174" if you want one section
OUT_CSV = "ecfr_subpart_h_rows.csv"


# ============================================================
# CHANGE: Build the correct eCFR XML endpoint.
# part / subpart / section are query params.
# ============================================================
def build_xml_url(
    date: str,
    title: int,
    part: str | None = None,
    subpart: str | None = None,
    section: str | None = None,
) -> str:
    base = f"https://www.ecfr.gov/api/versioner/v1/full/{date}/title-{title}.xml"

    params: dict[str, str] = {}
    if part:
        params["part"] = part
    if subpart:
        params["subpart"] = subpart
    if section:
        params["section"] = section

    return f"{base}?{urlencode(params)}" if params else base


# ============================================================
# CHANGE: Fetch XML with retries because the eCFR endpoint can be flaky.
# ============================================================
def fetch_xml(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.8",
    }

    last_err: Optional[Exception] = None

    for attempt in range(1, 4):
        try:
            r = requests.get(url, headers=headers, timeout=60)
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            last_err = e
            time.sleep(1.5 * attempt)

    assert last_err is not None
    raise last_err


# ============================================================
# Helpers
# ============================================================
def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def element_text(el: Optional[ET.Element]) -> str:
    if el is None:
        return ""
    return clean_text("".join(el.itertext()))


# ============================================================
# CHANGE: Parse HEAD text like:
# "§ 63.174 Standards: Connectors ..."
# into:
#   section_num = "63.174"
#   title = "Standards: Connectors ..."
# ============================================================
def parse_head_text(head_text: str) -> tuple[str, str]:
    head_text = clean_text(head_text)
    m = re.match(r"^.*?(\d+\.\d+)\s+(.*)$", head_text)
    if not m:
        return "", head_text
    return m.group(1), m.group(2)


# ============================================================
# CHANGE: Pull leading markers from paragraph text.
# Examples:
#   "(a) text..."
#   "(c)(1)(i) text..."
# Returns:
#   ["c", "1", "i"], "text..."
# ============================================================
def peel_leading_markers(text: str) -> tuple[list[str], str]:
    s = text.strip()
    tokens: list[str] = []

    while True:
        m = re.match(r"^\(([^)]+)\)\s*", s)
        if not m:
            break
        tokens.append(m.group(1).strip())
        s = s[m.end():]

    return tokens, s.strip()


# ============================================================
# CHANGE: Classify tokens with basic CFR-aware context.
# Handles lowercase "i" reasonably by using current_number.
# ============================================================
def classify_token(tok: str, current_number: Optional[int]) -> tuple[str, str | int]:
    tok = tok.strip()

    if re.fullmatch(r"\d+", tok):
        return "number", int(tok)

    if re.fullmatch(r"[A-Z]", tok):
        return "caps", tok

    # Multi-character lowercase romans are safely roman.
    if re.fullmatch(r"(?:ii|iii|iv|v|vi|vii|viii|ix|x|xi|xii|xiii|xiv|xv|xvi|xvii|xviii|xix|xx)", tok):
        return "roman", tok

    # Single lowercase i is ambiguous.
    if tok == "i":
        if current_number is not None:
            return "roman", tok
        return "letter", tok

    if re.fullmatch(r"[a-z]", tok):
        return "letter", tok

    return "unknown", tok


# ============================================================
# CHANGE: Apply marker chain like ["c","1","i"] to current state.
# ============================================================
def apply_marker_chain(
    tokens: list[str],
    letter: Optional[str],
    number: Optional[int],
    roman: Optional[str],
    caps: Optional[str],
) -> tuple[Optional[str], Optional[int], Optional[str], Optional[str]]:
    next_letter = letter
    next_number = number
    next_roman = roman
    next_caps = caps

    # IMPORTANT:
    # Start with NO carried-over number context for the first token of a new paragraph.
    # Only numbers encountered within THIS token chain should affect whether 'i' is roman.
    current_number: Optional[int] = None

    for idx, tok in enumerate(tokens):
        kind, value = classify_token(tok, current_number=current_number)

        if kind == "letter":
            next_letter = str(value)
            next_number = None
            next_roman = None
            next_caps = None
            current_number = None

        elif kind == "number":
            next_number = int(value)
            next_roman = None
            next_caps = None
            current_number = next_number

        elif kind == "roman":
            next_roman = str(value)
            next_caps = None

        elif kind == "caps":
            next_caps = str(value)

    return next_letter, next_number, next_roman, next_caps


def make_path(
    section_num: str,
    letter: Optional[str],
    number: Optional[int],
    roman: Optional[str],
    caps: Optional[str],
) -> str:
    path = f"§{section_num}"
    for tok in (letter, number, roman, caps):
        if tok is not None:
            path += f"({tok})"
    return path


# ============================================================
# CHANGE: Formula / extract content gets appended to the current row.
# ============================================================
def append_to_last_row(rows: List[Row], extra_text: str) -> None:
    extra_text = clean_text(extra_text)
    if not extra_text or not rows:
        return

    if rows[-1].Text:
        rows[-1].Text = f"{rows[-1].Text} {extra_text}"
    else:
        rows[-1].Text = extra_text


# ============================================================
# CHANGE: Parse one DIV8 section node.
# This matches the real eCFR XML structure you pasted.
# ============================================================
def parse_one_section(div8_el: ET.Element) -> List[Row]:
    rows: List[Row] = []

    section_num = div8_el.attrib.get("N", "").strip()
    head_el = div8_el.find("HEAD")
    head_text = element_text(head_el)

    head_section_num, title = parse_head_text(head_text)
    if not section_num:
        section_num = head_section_num

    letter: Optional[str] = None
    number: Optional[int] = None
    roman: Optional[str] = None
    caps: Optional[str] = None

    for child in div8_el:
        tag = local_name(child.tag)

        if tag == "HEAD":
            continue

        if tag == "P":
            full_text = element_text(child)
            tokens, body = peel_leading_markers(full_text)

            if tokens:
                letter, number, roman, caps = apply_marker_chain(
                    tokens,
                    letter=letter,
                    number=number,
                    roman=roman,
                    caps=caps,
                )

            path = make_path(section_num, letter, number, roman, caps)

            rows.append(
                Row(
                    Section=section_num,
                    Title=title,
                    Letter=letter,
                    Number=number,
                    Roman=roman,
                    Caps=caps,
                    Path=path,
                    Text=body,
                )
            )

        elif tag in {"FP", "FP-1", "FP-2", "FP-3"}:
            append_to_last_row(rows, element_text(child))

        elif tag == "EXTRACT":
            append_to_last_row(rows, element_text(child))

        elif tag == "CITA":
            # Skip citations for now.
            continue

        else:
            # Unknown child tags still get appended so content is not lost.
            append_to_last_row(rows, element_text(child))

    return rows


# ============================================================
# CHANGE: Parse either a single section XML response OR a larger
# subpart/part response containing multiple DIV8 sections.
# ============================================================
def parse_ecfr_xml(xml_text: str) -> List[Row]:
    root = ET.fromstring(xml_text)
    rows: List[Row] = []

    # If the response itself is one section
    if local_name(root.tag) == "DIV8" and root.attrib.get("TYPE") == "SECTION":
        rows.extend(parse_one_section(root))
        return rows

    # Otherwise search all descendants for DIV8 section nodes
    for el in root.iter():
        if local_name(el.tag) == "DIV8" and el.attrib.get("TYPE") == "SECTION":
            rows.extend(parse_one_section(el))

    return rows


# ============================================================
# CSV writer
# ============================================================
def write_rows_csv(rows: Iterable[Row], out_csv: str) -> None:
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["Section", "Title", "Letter", "Number", "Roman", "Caps", "Path", "Text"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def main() -> None:
    url = build_xml_url(
        date=DATE,
        title=TITLE,
        part=PART,
        subpart=SUBPART,
        section=SECTION,
    )

    print(f"Fetching: {url}")
    xml_text = fetch_xml(url)

    # Debug save
    with open("debug.xml", "w", encoding="utf-8") as f:
        f.write(xml_text)
    print("Saved debug.xml")

    rows = parse_ecfr_xml(xml_text)
    write_rows_csv(rows, OUT_CSV)

    print(f"Wrote {len(rows)} rows to {OUT_CSV}")


if __name__ == "__main__":
    main()