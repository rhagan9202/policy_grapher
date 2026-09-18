# Repository Guidelines

## Project Structure & Module Organization

Policy Grapher is split into a FastAPI backend and a Vite/React frontend. Backend code lives in `backend/src/policy_grapher/`, with routers in `routers/` and document-source logic in `sources/`; tests live in `backend/tests/`. Frontend code lives in `frontend/src/`, with views in `views/` and API helpers in `api/`. Sample policy data is in `data/samples/`. Project docs, specs, ADRs, sprint notes, and planning material live under `docs/`; follow `docs/CONVENTIONS.md`. `docs/solutions/` holds documented solutions to past problems (bugs, best practices, workflow patterns), organized by category with YAML frontmatter (`module`, `tags`, `problem_type`) — relevant when implementing or debugging in documented areas. `CONCEPTS.md` at the repo root holds the shared domain vocabulary — relevant when orienting to the codebase or discussing domain concepts.

## Build, Test, and Development Commands

- `./scripts/init-env.sh`: create a local `.env` with Neo4j and API secrets.
- `docker compose up --build`: build and run Neo4j, backend, and frontend.
- `cd backend && uv run pytest`: run backend tests, including lint via `tests/test_lint.py`.
- `cd backend && uv run pytest -m "not integration"`: skip Docker/Testcontainers-backed integration tests.
- `docker compose run --rm frontend npm test`: run frontend ESLint, TypeScript build checks, and Vitest.
- `docker compose run --rm frontend npm run build`: produce a production frontend build.

## Coding Style & Naming Conventions

Use 4-space indentation for Python and type-annotated Pydantic/FastAPI patterns already present in `backend/src/policy_grapher/`. Python modules and tests use snake_case names. Ruff is the backend lint gate. Frontend code is TypeScript/TSX with ESLint, React Hooks rules, and React Refresh checks. Keep React components in PascalCase and view tests named `*.test.tsx`.

## Standing rules

Set by the project owner: rules 1-2 on 2026-08-22, rules 3-5 on 2026-08-31, rules 6-7 on
2026-09-09. These are not judgement calls, and are not weighed against other considerations.

1. **Never close an unfinished sprint.** If any committed item, acceptance criterion, or
   [Definition of Done](docs/backlog/README.md#definition-of-done) gate is unmet, the sprint
   stays open. Do not close it "with caveats", do not record it as delivered-with-exceptions,
   and do not hand the decision back as a judgement call. Walk the gates literally before
   writing any `review.md`, `retrospective.md`, velocity row, or next sprint folder.

2. **Never leave a known bug unfixed.** A defect discovered while working is fixed in the code
   before that work is reported finished — whether it is in new code, pre-existing code, or
   someone else's. Filing a backlog story is not a substitute. Writing it into a sprint review
   or retrospective is not a substitute. If the fix needs a decision recorded, write the ADR
   *and* the fix, not one instead of the other.

3. **Check correctness before spending inference.** Never start a model-bound run over a
   dataset, fixture set, or prompt whose contents you have not inspected. Print the inputs
   and read them first — what sections they cover, how long they are, whether they are the
   kind of text the run is supposed to exercise. That check costs seconds and needs no model;
   the run costs tens of minutes of CPU inference on a model server that serialises, so it
   also blocks every other measurement while it goes. On 2026-08-31 a 40-minute canary
   baseline was recorded over 40 chunks that turned out to be cover pages and `PURPOSE`
   stubs — 35 of the 40 were rejections — because nobody looked at the selection first.
   **A long run is not a way to find out whether the inputs were right.**

4. **A gate must exercise the thing it gates.** A quality gate that runs a different model,
   a different prompt version, or a different decoding mode than the one that ships is
   measuring a different system, and its green tick means nothing about production. If cost
   forces a smaller stand-in, say so in the step's own name and comment, and do not let it
   count as the shipped model being gated. On 2026-08-31 a per-push gate was built around
   `llama3.2:3b` at recall 0.250 while the product ships `llama3.1:8b`: a prompt edit that
   helped 3b and wrecked 8b would have passed it green — the exact regression class the work
   existed to catch.

5. **Sequence the cheap checks first.** Within any piece of work, order the steps so that
   everything which can fail fast does fail fast: static inspection, then unit tests with no
   model, then a single short model call, then the long run. A defect found in step four that
   step one would have caught has cost the difference, and on a serialised CPU model server
   that difference is measured in hours.

6. **Read the whole code path before explaining behaviour.** A symptom tells you what
   happened, never why. Before asserting a cause — in a report, a commit message, a spec, an
   ADR, or a code comment — read the path from entry point to exit and cite the `file:line`
   that produces the behaviour. If you cannot point at that line, you have a hypothesis, and
   it must be written as one.

   Three failures on 2026-09-09, all the same shape. "Docker is gone from this machine",
   inferred from `which docker` inside a Flatpak sandbox whose `/usr` is not the host's —
   and re-run with the harness sandbox disabled, which is a different sandbox, so the second
   negative was the same namespace answering twice and was read as corroboration. A design
   spec claiming `changes/diff.py` pairs clauses only by section, inferred from the live
   `ADDED`/`REMOVED` counts after reading `_plan_changes` as far as the section rule and
   stopping thirty lines above `_pair_by_wording`. The same spec, revised, claiming a
   reviewer's approvals were unreachable by Triage, inferred from one query returning zero
   rows — while a same-document `IMPLEMENTS` over a `REMOVED` change was in fact producing a
   top-scored row asserting that DoDD 5000.01 implements itself.

   Two corollaries, because both were violated above. **A negative result is evidence about
   the run you did, not about the mechanism** — empty output, a missing binary, zero rows.
   And **re-running the same probe is not a second opinion**; corroboration has to come from
   a different instrument, or from the code.

7. **A spec is adversarially checked before it becomes a plan.** No implementation plan is
   written against a design document until an independent subagent has been dispatched to
   *refute* it and its findings have been resolved. Not to review it, not to summarise it —
   to attack it, told to assume it contains errors and to report only what it can show is
   wrong, citing `file:line`.

   Give it the specific claims to attack rather than "check this spec": the passes a function
   performs and in what order, the constants and their effect, which call sites exist, what a
   given `DELETE` can actually reach, whether a component the spec proposes to reuse is bound
   to something else. Name the ones you most suspect — the check is worth most where you are
   least sure, and a spec's author is the worst judge of that.

   Self-review does not substitute, and that is the whole point of the rule. On 2026-09-09
   two consecutive revisions of one design spec passed the author's own review and were both
   factually wrong about the code — the second was committed and pushed. An adversarial
   subagent returned fifteen findings on the third draft, including that the defect the spec
   existed to fix was not the defect that was happening: a same-document `IMPLEMENTS` was not
   invisible to Triage, it was producing a top-scored row claiming DoDD 5000.01 implements
   itself. The same wrong mental model writes and reviews; only a reader who does not hold it
   can see past it.

   **Verify the findings before acting on them.** A subagent is not an oracle and will
   overstate — of those fifteen, the load-bearing ones were confirmed against the code and
   the live graph first, and one piece of its reasoning was itself wrong. A refutation you
   have not checked is a hypothesis wearing a citation.

## Testing Guidelines

Backend tests use pytest and `test_*.py` naming. Mark tests that need live Neo4j or Testcontainers with `@pytest.mark.integration`; keep unit tests runnable without Docker where possible. Frontend tests use Vitest and Testing Library. Add tests for behavior changes, and run the smallest relevant test before the full suite.

## Commit & Pull Request Guidelines

Recent history uses concise Conventional Commit-style prefixes such as `fix:`, `feat:`, and `docs:`. Keep subject lines imperative and specific. Pull requests should include a short problem/solution summary, linked story or ADR when relevant, commands run, and screenshots for visible UI changes. If behavior changes, update the canonical spec or ADR in the same PR.

## Security & Configuration Tips

Do not commit `.env` or generated secrets. Use `.env.example` only for placeholders and `scripts/init-env.sh` for local credentials. Every route except `/health` expects bearer-token auth; avoid exposing local dev ports beyond loopback unless you have reviewed the proxy and CORS implications.
