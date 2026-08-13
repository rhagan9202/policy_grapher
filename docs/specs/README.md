# Specs

A spec answers "how should this behave?" — precisely enough that two engineers building
from it would produce the same thing, and a tester could write cases from it alone.

- `SPEC-NNN-<slug>.md` — feature and behavior specs
- `adr/ADR-NNN-<slug>.md` — decision records
- `architecture.md` — the canonical system overview

## Specs vs. ADRs

A **spec** describes behavior: what the system does. It's a living document — when behavior
changes, the spec changes with it, in the same pull request.

An **ADR** captures a decision and the reasoning behind it, frozen at the moment it was made.
Write one when a choice would be expensive to reverse or when someone six months from now
would otherwise ask "why on earth is it like this?" ADRs are never edited after acceptance —
superseded by a new ADR instead.

## Numbering

Sequential and permanent. Skipped numbers are fine; reused numbers are not.
