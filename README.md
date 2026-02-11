# cfr-to-excel

Convert CFR regulation plain text into a structured Excel sheet.

## Install Required Modules (Type this into Bash/Powershell/CLI)
pip install -r requirements.txt

## Run
python -m src.gui

### Preserve line breaks (default)
--join "\n"

### Join paragraph lines into a single wrapped line
--join " "
