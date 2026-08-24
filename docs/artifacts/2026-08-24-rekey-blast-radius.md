# Re-key blast radius: back-matter heading recognition

Measured 2026-08-24 by running `/tmp/measure_rekey.py` (throwaway, not committed) against
every PDF in `data/samples/` with `uv run --project backend python /tmp/measure_rekey.py`
from the repository root.

The script chunks each sample with `policy_grapher.chunking.chunk_pages` (today's rules,
unchanged) and separately counts, per page, lines matching the two heading patterns the
back-matter recognition change will use:

- `BACK_MATTER = re.compile(r"^(GLOSSARY|REFERENCES|ACRONYMS)\s*$")`
- `LETTERED = re.compile(r"^[A-Z]\.\d+(?:\.\d+)*\.\s+\S")`

Each matching line is a point where the change would open a new section, which changes the
`section_path` of the chunk containing it and re-keys that chunk's identity hash.

## Results

| Fixture | Chunks (current rules) | Lines that would open a back-matter section |
| --- | ---: | ---: |
| `500001p.pdf` | 38 | 6 |
| `500001p_2003.pdf` | 38 | 0 |
| `500001p_2020.pdf` | 34 | 6 |
| `500088p.pdf` | 94 | 6 |
| `514301p.pdf` | 42 | 2 |
| `818001m.pdf` | 203 | 6 |
| `850001_2014.pdf` | 121 | 2 |

**Total: 28 lines across all seven fixtures.**

## Notes

- `500001p_2003.pdf` (the 2003 edition of DoDD 5000.01) shows zero matching lines. That
  edition's back matter does not contain any line that matches either pattern verbatim, as
  measured by this script.
- The audit that motivated this measurement observed one affected chunk — ordinal 33 of
  `500001p_2020.pdf` — from reading that document's last six chunks. This survey covers all
  seven fixtures in `data/samples/`.
- The script counts matching lines, not chunks whose `section_path` changes; a fixture where
  several matching lines fall inside the section a preceding match already reopened would
  show more matching lines than newly re-keyed chunks. The 28 counted here is therefore an
  upper bound on the number of chunks Task 7's repair needs to cover, using the same patterns
  Task 7 will use.
