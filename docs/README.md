# Policy Grapher — Documentation

Feasibility demo and MVP for Policy Concierge: a knowledge graph over policy documents and the references that connect them.

This folder is the single source of truth for how this project is planned, specified, and
delivered. If a fact about the project lives anywhere, it lives here — once.

## Canonical documents

Each question below has exactly one authoritative answer. Everything else references it.

| If you're asking... | Read |
| --- | --- |
| Why does this project exist? | [Vision](planning/vision.md) |
| What are we building, and in what order? | [Roadmap](planning/roadmap.md) |
| What work is queued up? | [Backlog](backlog/backlog.md) |
| How is the system put together? | [Architecture](specs/architecture.md) |
| Why was it built that way? | [Decision records](specs/adr/) |
| What are we doing right now? | [Sprint 6 plan](sprints/sprint-06/plan.md) — unplanned; the [tech-debt surge](planning/roadmap.md#the-tech-debt-surge) closed at sprint 5 and Ready is empty |
| Where does this new document go? | [Conventions](CONVENTIONS.md) |

## Layout

```
docs/
├── planning/    vision, roadmap — the "why" and the "in what order"
├── backlog/     the ordered queue of work, plus epics and story detail
├── specs/       how things work: architecture, feature specs, decision records
├── sprints/     one folder per sprint: plan, review, retrospective
└── artifacts/   diagrams, research, notes, exports — supporting material
```

## Keeping this honest

Docs rot when nobody owns them. The upkeep rules — what to update when, and what to do
with a document that's gone stale — are in [CONVENTIONS.md](CONVENTIONS.md).

*Last reviewed: 2026-08-21*
