#!/usr/bin/env python3
"""Generate the XLSX manifest fixture from the CSV one — STORY-036.

Run from the repository root:

    uv --project backend run python scripts/make-xlsx-manifest.py

The fixture exists so ingestion can be tested against a real spreadsheet, and it
is generated rather than hand-built so that it and the CSV cannot drift into
describing different corpora. `test_manifest_xlsx.py` asserts they still agree,
so a stale fixture is a red build rather than a silent difference.
"""

import csv
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "samples" / "dod_policy_references_08122026.csv"
TARGET = ROOT / "data" / "samples" / "dod_policy_references_08122026.xlsx"


def main() -> None:
    with SOURCE.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Corpus"
    for row in rows:
        sheet.append(row)
    workbook.save(TARGET)
    print(f"wrote {TARGET.relative_to(ROOT)} — {len(rows) - 1} rows from {SOURCE.name}")


if __name__ == "__main__":
    main()
