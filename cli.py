from __future__ import annotations

import argparse
from pathlib import Path

from .config import ParseConfig
from .parser import CFRParser
from .writer import rows_to_excel
from .loaders import load_text_file

'''Returns None because this is setting up parameters and settings. No output is expected from this function. Will have
to modify after editing other sections in parser, model, config, and writer.'''

def main() -> None:
    ap = argparse.ArgumentParser(description="Convert CFR regulation plain text to structured Excel.")
    ap.add_argument("--part", type=int, default=63, help="CFR Part number (e.g., 63)")
    ap.add_argument("--input", type=Path, required=True, help="Input plain text file")
    ap.add_argument("--output", type=Path, required=True, help="Output .xlsx file")
    ap.add_argument(
        "--join",
        type=str,
        default="\\n",
        help=r'How to join multi-line paragraph text: "\n" (default) or " "',
    )
    ap.add_argument(
        "--keep-empty",
        action="store_true",
        help="If set, keep rows even when Text is empty (otherwise empty is skipped unless [Reserved]).",
    )
    args = ap.parse_args()

    join_lines_with = "\n" if args.join == r"\n" else args.join

    cfg = ParseConfig(
        part_number=args.part,
        join_lines_with=join_lines_with,
        skip_empty_text_rows=(not args.keep_empty),
    )

    lines = load_text_file(args.input)
    parser = CFRParser(cfg)
    rows = parser.parse_lines(lines)

    rows_to_excel(rows, str(args.output))
    print(f"Wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
