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

## Task 8: decisions survive the re-key, proved as a deterministic test

Measured 2026-08-24. `backend/tests/test_rebuild.py::test_a_rebuild_carries_an_approval_across_a_full_rekey`
starts from the existing `reviewed_graph` fixture (`514301p.pdf` implementing `500001p_2003.pdf`,
one proposal approved, one rejected), monkeypatches `policy_grapher.chunking.section_heading` so
every heading it returns gets a `-REKEYED` suffix, and rebuilds only the org-tier edition
(`514301p.pdf`) through `rebuild_derived` with the deterministic `ModalSentenceExtractor`. This
re-keys every chunk and every obligation of the rebuilt edition — strictly more of the graph than
commit 79d40e9's real change, which moves only back matter.

Obligation ids for the rebuilt edition, before and after (11 obligations, fully disjoint sets —
none survived unchanged):

```
before: 0b2434a902d0d0d998f7c07604221d8e, 34579a37f23fddd3187de4385d391830,
         47cb219ae870238447eb1088399be9c6, 7a818ad30be4c0952673caf36267f95f,
         9438731bfa5639a565526f9df6270674, ad942ab31abd9b1a6a7a2e08c881e7e9,
         c122801eeca5e9ddde5f09859a0eeb93, e2c46f023b7f64629374bce6110a04c4,
         e7e0f01573614fe86ac8d643b7903a62, e9c3fc56760d9032c9b56638b14c5c23,
         f188217e76db5f19fca4bfd42c873b5d

after:   02cec1ea8061abb7a7088644a605c063, 1039c791adcc74de58a9a2b996fccf71,
         4252ffd56a6d18471904d236f5d17476, 4b9acd30e651515b927f2470d7151a8f,
         4de903ba8aaa93f35aa35ed51a365e15, 534368bb916f59ff9bb8852ead9f722c,
         85c978b2e89cebf3710fb83ebb156f32, 9c22009f14584680e3261cf66bcafbf9,
         bfa0bab74468fa41d83d3ddeb134b971, cafe60f6b2c46537f8639a2827b2dc76,
         fd0dd11152926ec5f3909dee7df4dd0f
```

The approved pair (source `47cb219ae8...`, target `64699dcd0e...`) repointed to source
`1039c791ad...` (target unchanged, since the higher-tier edition was not rebuilt). The rejected
pair's source repointed the same way, to `1039c791ad...` as well — same obligation, two decisions
against two different targets. `rebuild_derived`'s report: `decisions_repointed: 2, promoted: 1,
suppressed: 1, unpromotable: 0`. The approved `IMPLEMENTS` edge exists at the new ids; the rejected
pair has no edge, at either the old or the new ids; both decisions' verdicts (`approve` / `reject`)
are unchanged.

Deliberate-failure check, run before trusting the assertions above: `repoint_decisions` in
`backend/src/policy_grapher/links/decisions.py` was temporarily edited to `return 0` immediately
(no write), and the test was run in isolation. It failed exactly where expected:

```
>       assert alice["source_id"] != approved[0], "alice's decision was not repointed"
E       AssertionError: alice's decision was not repointed
E       assert '47cb219ae870238447eb1088399be9c6' != '47cb219ae870238447eb1088399be9c6'
```

The change was then reverted (`git diff` confirmed no residual diff) and the test re-run green.
Full backend suite: 578 passed, 5 skipped (up from the 577/5 baseline by exactly the one new test).

Separately, a cheap live check confirmed deployment wiring (not the repair itself, which needs a
real extractor): `docker compose up -d --build backend worker` came up healthy; `POST /ingest` for
`500001p_2020.pdf` succeeded; `POST /documents/dodd-5000-01/versions/dodd-5000-01@2020-09-09/rebuild`
ran to `"state":"finished"` with the default null extractor, and `GET /rebuilds/{run_id}` returned
`counts` carrying `"decisions_repointed":0` — the field is deployed and reaches the API response,
with zero obligations extracted as expected from the null adapter.
