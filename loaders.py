from __future__ import annotations

from pathlib import Path
from typing import List
import re
import urllib.request


# ---- Cleaning / preprocessing ----

_HEADER_FOOTER_PATTERNS = [
    r"^\s*Page\s+\d+\s*(of\s+\d+)?\s*$",
    r"^\s*\d+\s*$",  # bare page number lines
    r"^\s*Electronic Code of Federal Regulations\s*$",
    r"^\s*eCFR\s*$",
    r"^\s*Federal Register\s*/\s*Vol\..*$",
    r"^\s*U\.S\.\s*Government Publishing Office.*$",
]

_HEADER_FOOTER_RE = re.compile("|".join(f"(?:{p})" for p in _HEADER_FOOTER_PATTERNS), re.IGNORECASE)

#Strips headers and gooters when CTRL + A the regs and posting them in the .txt file
def strip_headers_footers(lines: List[str]) -> List[str]:
    cleaned: List[str] = []
    for ln in lines:
        s = ln.strip()
        if not s:
            cleaned.append("")  # keep blank lines
            continue
        if _HEADER_FOOTER_RE.match(s):
            continue
        cleaned.append(ln)
    return cleaned


def normalize_lines(text: str) -> List[str]:
    # Normalize line endings, keep as lines (no trailing \n)
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


# ---- TXT loader ----
#Bread and Butter. Dont Fuck with this.
def load_text_file(path: Path, encoding: str = "utf-8") -> List[str]:
    return normalize_lines(path.read_text(encoding=encoding))


# ---- HTML loaders ----
#CLEAN UP DIS SHIT; DONT WORK! (BLocked by Webpage, API possible solution w/ scraping limits. eCFR offers API)
def _html_to_text_lines(html: str) -> List[str]:
    """
    Convert HTML -> plain text lines suitable for the existing line-based parser.
    Uses BeautifulSoup for best results.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError as e:
        raise RuntimeError(
            "HTML support requires beautifulsoup4. Install it with: python -m pip install beautifulsoup4 lxml"
        ) from e

    soup = BeautifulSoup(html, "lxml")  # falls back if lxml not present, but we recommend it

    # Remove script/style
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # Convert to text; separator puts tags on newlines so markers/sections survive more often
    text = soup.get_text(separator="\n")

    # Light cleanup: collapse 3+ blank lines to 2
    lines = normalize_lines(text)
    out: List[str] = []
    blank_run = 0
    for ln in lines:
        if ln.strip() == "":
            blank_run += 1
            if blank_run <= 2:
                out.append("")
        else:
            blank_run = 0
            out.append(ln.rstrip())
    return out

#CLEAN UP DIS SHIT; DONT WORK! (BLocked by Webpage, API possible solution w/ scraping limits)
def load_html_file(path: Path, encoding: str = "utf-8") -> List[str]:
    html = path.read_text(encoding=encoding)
    return _html_to_text_lines(html)


def load_html_url(url: str, timeout: int = 30) -> List[str]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; CFRParser/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        # Try utf-8 first; fall back if needed
        try:
            html = raw.decode("utf-8")
        except UnicodeDecodeError:
            html = raw.decode("latin-1")
    return _html_to_text_lines(html)
