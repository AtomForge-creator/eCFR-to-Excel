from __future__ import annotations

import re
import time
import threading
import queue
from dataclasses import asdict, dataclass
from typing import Iterable, List, Optional
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

import requests
import pandas as pd
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


# ============================================================
# DATA MODEL
# ============================================================
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


# ============================================================
# API / PARSER HELPERS
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


def parse_head_text(head_text: str) -> tuple[str, str]:
    head_text = clean_text(head_text)
    m = re.match(r"^.*?(\d+\.\d+)\s+(.*)$", head_text)
    if not m:
        return "", head_text
    return m.group(1), m.group(2)


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


def classify_token(tok: str, current_number: Optional[int]) -> tuple[str, str | int]:
    tok = tok.strip()

    if re.fullmatch(r"\d+", tok):
        return "number", int(tok)

    if re.fullmatch(r"[A-Z]", tok):
        return "caps", tok

    if re.fullmatch(r"(?:ii|iii|iv|v|vi|vii|viii|ix|x|xi|xii|xiii|xiv|xv|xvi|xvii|xviii|xix|xx)", tok):
        return "roman", tok

    if tok == "i":
        if current_number is not None:
            return "roman", tok
        return "letter", tok

    if re.fullmatch(r"[a-z]", tok):
        return "letter", tok

    return "unknown", tok


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

    # Important: do not leak previous paragraph numbering into the first token
    current_number: Optional[int] = None

    for tok in tokens:
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


def append_to_last_row(rows: List[Row], extra_text: str) -> None:
    extra_text = clean_text(extra_text)
    if not extra_text or not rows:
        return

    if rows[-1].Text:
        rows[-1].Text = f"{rows[-1].Text} {extra_text}"
    else:
        rows[-1].Text = extra_text


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
            continue

        else:
            append_to_last_row(rows, element_text(child))

    return rows


def parse_ecfr_xml(xml_text: str) -> List[Row]:
    root = ET.fromstring(xml_text)
    rows: List[Row] = []

    if local_name(root.tag) == "DIV8" and root.attrib.get("TYPE") == "SECTION":
        rows.extend(parse_one_section(root))
        return rows

    for el in root.iter():
        if local_name(el.tag) == "DIV8" and el.attrib.get("TYPE") == "SECTION":
            rows.extend(parse_one_section(el))

    return rows


def write_rows_excel(rows: Iterable[Row], out_file: str) -> None:
    df = pd.DataFrame([asdict(r) for r in rows])

    if not df.empty:
        df = df.sort_values(by=["Section", "Path"], kind="stable")

    with pd.ExcelWriter(out_file, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="eCFR Rows")

        ws = writer.sheets["eCFR Rows"]
        widths = {
            "A": 14,  # Section
            "B": 60,  # Title
            "C": 10,  # Letter
            "D": 10,  # Number
            "E": 10,  # Roman
            "F": 10,  # Caps
            "G": 24,  # Path
            "H": 120, # Text
        }
        for col, width in widths.items():
            ws.column_dimensions[col].width = width


# ============================================================
# GUI
# ============================================================
class App(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("eCFR XML to Excel")
        self.geometry("900x650")

        self.log_q: queue.Queue[str] = queue.Queue()
        self.worker: Optional[threading.Thread] = None

        self.date_var = tk.StringVar(value="2024-01-01")
        self.title_var = tk.StringVar(value="40")
        self.part_var = tk.StringVar(value="63")
        self.subpart_var = tk.StringVar(value="H")
        self.section_var = tk.StringVar(value="")
        self.out_var = tk.StringVar(value="ecfr_export.xlsx")

        self._build_ui()
        self.after(100, self._drain_logs)

    def _build_ui(self):
        pad = {"padx": 8, "pady": 6}

        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")

        ttk.Label(top, text="Date (YYYY-MM-DD)").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(top, textvariable=self.date_var, width=18).grid(row=0, column=1, sticky="w", **pad)

        ttk.Label(top, text="Title").grid(row=0, column=2, sticky="w", **pad)
        ttk.Entry(top, textvariable=self.title_var, width=10).grid(row=0, column=3, sticky="w", **pad)

        ttk.Label(top, text="Part").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(top, textvariable=self.part_var, width=18).grid(row=1, column=1, sticky="w", **pad)

        ttk.Label(top, text="Subpart").grid(row=1, column=2, sticky="w", **pad)
        ttk.Entry(top, textvariable=self.subpart_var, width=10).grid(row=1, column=3, sticky="w", **pad)

        ttk.Label(top, text="Section (optional)").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(top, textvariable=self.section_var, width=18).grid(row=2, column=1, sticky="w", **pad)

        ttk.Label(top, text="Output Excel").grid(row=3, column=0, sticky="w", **pad)
        ttk.Entry(top, textvariable=self.out_var, width=55).grid(row=3, column=1, columnspan=2, sticky="we", **pad)
        ttk.Button(top, text="Browse", command=self.choose_output).grid(row=3, column=3, sticky="w", **pad)

        note = (
            "Leave Section blank to export the whole subpart. "
            "Example: Title 40, Part 63, Subpart H, Section 63.174"
        )
        ttk.Label(top, text=note).grid(row=4, column=0, columnspan=4, sticky="w", **pad)

        controls = ttk.Frame(self, padding=(12, 0, 12, 12))
        controls.pack(fill="x")

        self.run_btn = ttk.Button(controls, text="Run Export", command=self.on_run)
        self.run_btn.pack(side="left")

        self.progress = ttk.Progressbar(controls, mode="indeterminate", length=260)
        self.progress.pack(side="left", padx=12)

        log_frame = ttk.LabelFrame(self, text="Log", padding=12)
        log_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.log_text = tk.Text(log_frame, wrap="word")
        self.log_text.pack(fill="both", expand=True)

    def choose_output(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel Workbook", "*.xlsx")],
        )
        if path:
            self.out_var.set(path)

    def log(self, msg: str):
        self.log_q.put(msg)

    def _drain_logs(self):
        try:
            while True:
                msg = self.log_q.get_nowait()
                self.log_text.insert("end", msg + "\n")
                self.log_text.see("end")
        except queue.Empty:
            pass
        self.after(100, self._drain_logs)

    def on_run(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Running", "An export is already running.")
            return

        try:
            date = self.date_var.get().strip()
            title = int(self.title_var.get().strip())
            part = self.part_var.get().strip()
            subpart = self.subpart_var.get().strip()
            section = self.section_var.get().strip() or None
            out_file = self.out_var.get().strip()

            if not date or not part or not subpart or not out_file:
                messagebox.showerror("Error", "Date, Part, Subpart, and Output file are required.")
                return

        except ValueError:
            messagebox.showerror("Error", "Title must be a whole number.")
            return

        self.run_btn.configure(state="disabled")
        self.progress.start(10)
        self.log_text.delete("1.0", "end")

        self.worker = threading.Thread(
            target=self._worker_run,
            args=(date, title, part, subpart, section, out_file),
            daemon=True,
        )
        self.worker.start()

    def _worker_run(self, date: str, title: int, part: str, subpart: str, section: Optional[str], out_file: str):
        try:
            url = build_xml_url(
                date=date,
                title=title,
                part=part,
                subpart=subpart,
                section=section,
            )

            self.log(f"Fetching: {url}")
            xml_text = fetch_xml(url)

            self.log("Parsing XML...")
            rows = parse_ecfr_xml(xml_text)
            self.log(f"Parsed rows: {len(rows)}")

            if not rows:
                self.log("No rows were found. Check the Title / Part / Subpart / Section values.")
            else:
                self.log("Writing Excel file...")
                write_rows_excel(rows, out_file)
                self.log(f"Saved: {out_file}")

                section_count = len({r.Section for r in rows})
                self.log(f"Sections exported: {section_count}")

        except Exception as e:
            self.log(f"Error: {e}")
        finally:
            self.after(0, self._finish_run)

    def _finish_run(self):
        self.progress.stop()
        self.run_btn.configure(state="normal")


if __name__ == "__main__":
    App().mainloop()
