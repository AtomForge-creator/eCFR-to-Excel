from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path

from .config import ParseConfig
from .parser import CFRParser
from .writer import rows_to_excel
from .loaders import (
    load_text_file,
    load_html_file,
    load_html_url,
    strip_headers_footers,
)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CFR Text/HTML → Excel Converter")
        self.geometry("820x360")
        self.resizable(False, False)

        # Input mode: "txt" | "html_file" | "html_url"
        self.input_mode = tk.StringVar(value="txt")

        self.input_path = tk.StringVar()
        self.input_url = tk.StringVar()

        self.output_path = tk.StringVar()
        self.part_number = tk.StringVar(value="63")
        self.join_mode = tk.StringVar(value="\\n")  # "\\n" or " "
        self.strip_hf = tk.BooleanVar(value=True)

        self._build()
        self._toggle_input_mode()

    def _build(self):
        pad = {"padx": 10, "pady": 6}

        # Mode selection
        tk.Label(self, text="Input source:").grid(row=0, column=0, sticky="w", **pad)

        mode_frame = tk.Frame(self)
        mode_frame.grid(row=0, column=1, sticky="w", **pad)

        tk.Radiobutton(mode_frame, text="TXT file", variable=self.input_mode, value="txt",
                       command=self._toggle_input_mode).pack(side="left", padx=6)
        tk.Radiobutton(mode_frame, text="HTML file", variable=self.input_mode, value="html_file",
                       command=self._toggle_input_mode).pack(side="left", padx=6)
        tk.Radiobutton(mode_frame, text="eCFR URL", variable=self.input_mode, value="html_url",
                       command=self._toggle_input_mode).pack(side="left", padx=6)

        # Input file row
        tk.Label(self, text="Input file:").grid(row=1, column=0, sticky="w", **pad)
        self.input_entry = tk.Entry(self, textvariable=self.input_path, width=78)
        self.input_entry.grid(row=1, column=1, sticky="w", **pad)
        self.browse_btn = tk.Button(self, text="Browse…", command=self.browse_input)
        self.browse_btn.grid(row=1, column=2, **pad)

        # URL row
        tk.Label(self, text="eCFR URL:").grid(row=2, column=0, sticky="w", **pad)
        self.url_entry = tk.Entry(self, textvariable=self.input_url, width=78)
        self.url_entry.grid(row=2, column=1, sticky="w", **pad)
        self.url_hint = tk.Label(self, text="Paste a full eCFR page URL (section/subpart page).")
        self.url_hint.grid(row=2, column=2, sticky="w", padx=10, pady=6)

        # Output row
        tk.Label(self, text="Output .xlsx file:").grid(row=3, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self.output_path, width=78).grid(row=3, column=1, sticky="w", **pad)
        tk.Button(self, text="Save As…", command=self.browse_output).grid(row=3, column=2, **pad)

        # Options
        tk.Label(self, text="CFR Part:").grid(row=4, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self.part_number, width=10).grid(row=4, column=1, sticky="w", **pad)

        tk.Label(self, text="Join lines with:").grid(row=5, column=0, sticky="w", **pad)
        join_frame = tk.Frame(self)
        join_frame.grid(row=5, column=1, sticky="w", **pad)
        tk.Radiobutton(join_frame, text="\\n (preserve line breaks)", variable=self.join_mode, value="\\n").pack(anchor="w")
        tk.Radiobutton(join_frame, text="space (single paragraph line)", variable=self.join_mode, value=" ").pack(anchor="w")

        tk.Checkbutton(self, text="Strip headers/footers (recommended for messy exports)",
                       variable=self.strip_hf).grid(row=6, column=1, sticky="w", padx=10, pady=6)

        # Run
        tk.Button(self, text="Convert to Excel", command=self.run_convert, height=2, width=22)\
            .grid(row=7, column=1, sticky="w", padx=10, pady=14)

        tk.Label(self, text="Tip: If using eCFR URL, choose a page that contains the '§ 63.xxx' section lines.")\
            .grid(row=8, column=0, columnspan=3, sticky="w", padx=10, pady=0)

    def _toggle_input_mode(self):
        mode = self.input_mode.get()

        # Enable/disable file widgets
        file_enabled = mode in ("txt", "html_file")
        self.input_entry.configure(state="normal" if file_enabled else "disabled")
        self.browse_btn.configure(state="normal" if file_enabled else "disabled")

        # Enable/disable URL widgets
        url_enabled = mode == "html_url"
        self.url_entry.configure(state="normal" if url_enabled else "disabled")

    def browse_input(self):
        mode = self.input_mode.get()
        if mode == "txt":
            types = [("Text files", "*.txt"), ("All files", "*.*")]
        else:
            types = [("HTML files", "*.html;*.htm"), ("All files", "*.*")]

        path = filedialog.askopenfilename(title="Select input file", filetypes=types)
        if path:
            self.input_path.set(path)

            # Suggest output name if not set
            if not self.output_path.get():
                p = Path(path)
                suggested = p.with_suffix(".xlsx")
                self.output_path.set(str(suggested))

    def browse_output(self):
        path = filedialog.asksaveasfilename(
            title="Save output Excel file",
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx")]
        )
        if path:
            self.output_path.set(path)

    def _get_lines(self) -> list[str]:
        mode = self.input_mode.get()

        if mode == "txt":
            in_path = self.input_path.get().strip()
            if not in_path:
                raise RuntimeError("Please select an input .txt file.")
            lines = load_text_file(Path(in_path))

        elif mode == "html_file":
            in_path = self.input_path.get().strip()
            if not in_path:
                raise RuntimeError("Please select an input .html file.")
            lines = load_html_file(Path(in_path))

        elif mode == "html_url":
            url = self.input_url.get().strip()
            if not url:
                raise RuntimeError("Please paste an eCFR URL.")
            lines = load_html_url(url)

        else:
            raise RuntimeError(f"Unknown input mode: {mode}")

        if self.strip_hf.get():
            lines = strip_headers_footers(lines)

        return lines

    def run_convert(self):
        out_path = self.output_path.get().strip()
        if not out_path:
            messagebox.showerror("Missing output", "Please choose where to save the output .xlsx file.")
            return

        try:
            part = int(self.part_number.get().strip())
        except ValueError:
            messagebox.showerror("Invalid Part", "CFR Part must be a number (e.g., 63).")
            return

        join_lines_with = "\n" if self.join_mode.get() == "\\n" else " "

        try:
            output_file = Path(out_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)

            cfg = ParseConfig(part_number=part, join_lines_with=join_lines_with)
            parser = CFRParser(cfg)

            lines = self._get_lines()
            rows = parser.parse_lines(lines)

            rows_to_excel(rows, str(output_file))
            messagebox.showinfo("Success", f"Converted {len(rows)} rows.\nSaved to:\n{output_file}")
        except Exception as e:
            messagebox.showerror("Error", f"Conversion failed:\n{e}")


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
