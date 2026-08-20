# Repository Guidelines

## Project Structure & Module Organization

Policy Grapher is split into a FastAPI backend and a Vite/React frontend. Backend code lives in `backend/src/policy_grapher/`, with routers in `routers/` and document-source logic in `sources/`; tests live in `backend/tests/`. Frontend code lives in `frontend/src/`, with views in `views/` and API helpers in `api/`. Sample policy data is in `data/samples/`. Project docs, specs, ADRs, sprint notes, and planning material live under `docs/`; follow `docs/CONVENTIONS.md`.

## Build, Test, and Development Commands

- `./scripts/init-env.sh`: create a local `.env` with Neo4j and API secrets.
- `docker compose up --build`: build and run Neo4j, backend, and frontend.
- `cd backend && uv run pytest`: run backend tests, including lint via `tests/test_lint.py`.
- `cd backend && uv run pytest -m "not integration"`: skip Docker/Testcontainers-backed integration tests.
- `docker compose run --rm frontend npm test`: run frontend ESLint, TypeScript build checks, and Vitest.
- `docker compose run --rm frontend npm run build`: produce a production frontend build.

## Coding Style & Naming Conventions

Use 4-space indentation for Python and type-annotated Pydantic/FastAPI patterns already present in `backend/src/policy_grapher/`. Python modules and tests use snake_case names. Ruff is the backend lint gate. Frontend code is TypeScript/TSX with ESLint, React Hooks rules, and React Refresh checks. Keep React components in PascalCase and view tests named `*.test.tsx`.

## Testing Guidelines

Backend tests use pytest and `test_*.py` naming. Mark tests that need live Neo4j or Testcontainers with `@pytest.mark.integration`; keep unit tests runnable without Docker where possible. Frontend tests use Vitest and Testing Library. Add tests for behavior changes, and run the smallest relevant test before the full suite.

## Commit & Pull Request Guidelines

Recent history uses concise Conventional Commit-style prefixes such as `fix:`, `feat:`, and `docs:`. Keep subject lines imperative and specific. Pull requests should include a short problem/solution summary, linked story or ADR when relevant, commands run, and screenshots for visible UI changes. If behavior changes, update the canonical spec or ADR in the same PR.

## Security & Configuration Tips

Do not commit `.env` or generated secrets. Use `.env.example` only for placeholders and `scripts/init-env.sh` for local credentials. Every route except `/health` expects bearer-token auth; avoid exposing local dev ports beyond loopback unless you have reviewed the proxy and CORS implications.
