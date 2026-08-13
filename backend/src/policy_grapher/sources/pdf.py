"""Extract a DoD issuance PDF into a document and its cited references.

Five stages, each a pure function: detect the format, locate the references
section, split it into entries, take each entry's identifier, normalise the
identifier to the vocabulary the corpus uses. Stage 2 is where extraction
fails catastrophically when it fails at all, so it reports "not found"
explicitly rather than returning an empty string.
"""

from pathlib import Path

from pypdf import PdfReader


def text_of(path: Path) -> str:
    """Every page's text, joined by newlines."""
    return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
