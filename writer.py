from __future__ import annotations

from typing import Iterable
import pandas as pd

from .model import Row

#NEEDS DEEPER COLUMNS
COLUMNS = ["Section", "Title", "Letter", "Number", "Roman", "Caps", "Path", "Text"]


def rows_to_excel(rows: Iterable[Row], outfile: str, sheet_name: str = "Sheet1") -> None:
    df = pd.DataFrame([r.__dict__ for r in rows], columns=COLUMNS)

    with pd.ExcelWriter(outfile, engine="openpyxl") as xl:
        df.to_excel(xl, index=False, sheet_name=sheet_name)
