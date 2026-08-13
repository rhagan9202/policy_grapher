"""Read the reference CSV into an immutable, database-free structure.

Everything here is pure: no Neo4j, no settings, no I/O beyond reading the file.
"""

import ast
import csv
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

EXPECTED_COLUMNS = ["Document Name", "References", "Type"]

_PARENTHESISED = re.compile(r"\([^)]*\)")
_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]")


class CsvSourceError(ValueError):
    """The CSV could not be located or could not be read as expected."""


def resolve_csv_path(filename: str, data_dir: Path) -> Path:
    """Resolve a bare filename under data_dir, refusing anything that escapes it."""
    if not filename or Path(filename).name != filename:
        raise CsvSourceError(
            f"{filename!r} is not a bare filename; give a name, not a path."
        )

    root = data_dir.resolve()
    path = (root / filename).resolve()
    if not path.is_relative_to(root):
        raise CsvSourceError(f"{filename!r} resolves outside the data directory.")
    if not path.is_file():
        raise CsvSourceError(f"{filename!r} was not found in the data directory.")
    return path


def canonical_name(name: str) -> str:
    """Aggressive normalisation used only to spot near-duplicate names."""
    without_parens = _PARENTHESISED.sub("", name)
    return _NON_ALPHANUMERIC.sub("", without_parens.casefold())


@dataclass(frozen=True)
class CorpusRow:
    name: str
    reference_role: str
    references: tuple[str, ...]


@dataclass(frozen=True)
class ParsedCorpus:
    rows: tuple[CorpusRow, ...]
    corpus_names: frozenset[str]
    external_names: frozenset[str]
    edges: tuple[tuple[str, str], ...]
    self_references_skipped: int
    suspected_duplicates: tuple[tuple[str, ...], ...]

    @property
    def all_names(self) -> frozenset[str]:
        return self.corpus_names | self.external_names


def _parse_references(cell: str, document: str) -> tuple[str, ...]:
    try:
        value = ast.literal_eval(cell)
    except (ValueError, SyntaxError) as exc:
        raise CsvSourceError(
            f"References for {document!r} are not a valid Python list: {exc}"
        ) from exc
    if not isinstance(value, (list, tuple)):
        raise CsvSourceError(
            f"References for {document!r} parsed as {type(value).__name__}, not a list."
        )
    return tuple(str(item).strip() for item in value if str(item).strip())


def _find_suspected_duplicates(names: frozenset[str]) -> tuple[tuple[str, ...], ...]:
    groups: dict[str, list[str]] = defaultdict(list)
    for name in sorted(names):
        groups[canonical_name(name)].append(name)
    return tuple(
        tuple(group) for _, group in sorted(groups.items()) if len(group) > 1
    )


def parse_corpus(path: Path) -> ParsedCorpus:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != EXPECTED_COLUMNS:
            raise CsvSourceError(
                f"Expected columns {EXPECTED_COLUMNS}, found {reader.fieldnames}."
            )
        raw_rows = list(reader)

    rows: list[CorpusRow] = []
    edges: set[tuple[str, str]] = set()
    self_references = 0

    for raw in raw_rows:
        name = (raw["Document Name"] or "").strip()
        if not name:
            raise CsvSourceError("A row has an empty 'Document Name'.")
        role = (raw["Type"] or "").strip()
        references = _parse_references(raw["References"] or "[]", name)

        rows.append(CorpusRow(name=name, reference_role=role, references=references))

        for target in references:
            if target == name:
                self_references += 1
                continue
            edges.add((name, target))

    corpus_names = frozenset(row.name for row in rows)
    referenced = frozenset(t for _, t in edges) | frozenset(
        target for row in rows for target in row.references
    )
    external_names = referenced - corpus_names

    return ParsedCorpus(
        rows=tuple(rows),
        corpus_names=corpus_names,
        external_names=external_names,
        edges=tuple(sorted(edges)),
        self_references_skipped=self_references,
        suspected_duplicates=_find_suspected_duplicates(corpus_names | external_names),
    )
