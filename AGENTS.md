# AGENTS.md

This file guides coding agents working in `C:\Users\Ashmil P\Desktop\shortmaker`.

## Scope

- Applies to the whole repository.
- There was no existing `AGENTS.md` in this repo when this file was created.
- No Cursor rules were found in `.cursor/rules/`.
- No `.cursorrules` file was found.
- No Copilot instructions were found in `.github/copilot-instructions.md`.
- If any of those files are added later, treat them as higher-priority repo guidance and update this file.

## Repository Overview

- Backend: FastAPI app in `backend/`.
- Frontend: Vite + React app in `frontend/`.
- Shared utilities: `utils/`.
- Local dev reload runner: `dev_server.py`.
- Python dependency metadata: `pyproject.toml`, `requirements.txt`, `uv.lock`.
- Frontend package manifest: `frontend/package.json` and `frontend/package-lock.json`.
- Generated/runtime data lands in `outputs/` and `.env.json`; do not treat these as source files.

## Tooling Detected

- Python: `>=3.10,<3.13` from `pyproject.toml`.
- Backend server: `uvicorn` serving `backend.main:app`.
- Backend framework: FastAPI + Pydantic.
- Frontend: React 19 + Vite 6 + TypeScript config.
- Frontend type checking is enforced by `tsc -b` during build.
- No repo-level Python linter config was found (`ruff`, `flake8`, `mypy`, etc. not configured here).
- No frontend lint config was found (`eslint`/`prettier` not configured here).
- No automated test suite or test config was found (`pytest`, `vitest`, `jest`, `playwright`, `cypress` were not present).

## Working Norms For Agents

- Preserve existing architecture; do not introduce a new framework or major dependency without a strong reason.
- Prefer small, local edits over broad refactors.
- Keep backend and frontend changes separate unless a feature truly spans both.
- Avoid modifying generated outputs, runtime job artifacts, or stored secrets unless the task explicitly requires it.
- Do not commit `.env`, `.env.json`, API keys, OAuth secrets, tokens, or other credentials.
- Treat `outputs/` as ephemeral runtime state, not as source-controlled code.

## Setup Commands

### Backend setup

```bash
uv sync
```

Alternative if `uv` is unavailable:

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Optional local Whisper dependencies:

```bash
pip install -r requirements-local.txt
```

### Frontend setup

```bash
cd frontend && npm install
```

## Run Commands

### Backend dev server

Preferred reload runner on Windows:

```bash
python dev_server.py
```

Direct server command:

```bash
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Direct server with reload:

```bash
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Notes:

- The README warns that `--reload` restarts in-flight jobs; prefer `python dev_server.py` for scoped reload behavior.
- Backend serves the API and, when built, can serve frontend assets.

### Frontend dev server

```bash
cd frontend && npm run dev
```

Default Vite port is `5173` per `frontend/vite.config.ts`.

## Build Commands

### Frontend build

```bash
cd frontend && npm run build
```

What it does:

- Runs `tsc -b`.
- Runs `vite build`.
- Writes production assets to `frontend/dist`.

### Backend build

- There is no separate backend build step.
- Backend is interpreted Python; validate by starting the app successfully.

## Lint And Typecheck Commands

### Commands that actually exist today

- Frontend type/build check: `cd frontend && npm run build`
- Backend syntax/import smoke check: `uv run python -m compileall backend utils dev_server.py`

### Important caveat

- There is currently no dedicated lint script in this repository.
- There is currently no configured formatter command in this repository.
- There is currently no dedicated standalone frontend typecheck script; `npm run build` is the closest built-in check.

## Test Commands

### Current repo state

- No automated tests were found.
- No `tests/` directory or `test_*.py`, `*.test.ts`, `*.spec.ts`, or similar test files were found.
- No `pytest`, `vitest`, or `jest` config was found.

### What agents should do instead

- For frontend-only edits, run `cd frontend && npm run build`.
- For backend-only edits, start the app or run a Python syntax smoke check.
- For cross-stack edits, run both backend and frontend validation commands.

### Single-test guidance

- There is no project-native single-test command yet because no test runner is configured.
- If a Python test suite is introduced later, the expected single-test form should be:

```bash
uv run pytest path/to/test_file.py::test_name
```

- If a Vitest suite is introduced later, the expected single-test form should be:

```bash
cd frontend && npx vitest run path/to/file.test.ts -t "test name"
```

## Code Style Guidelines

## General

- Follow the existing file's style before applying global preferences.
- Keep diffs narrow and practical.
- Prefer explicit behavior over clever abstractions.
- Add comments only when a block is genuinely non-obvious.
- Favor simple control flow and helper functions over deeply nested logic.

## Imports

- Group imports by standard library, third-party, then local modules.
- Keep import style consistent within the file you are editing.
- Backend commonly uses `from x import y` for targeted imports and relative imports inside `backend/`.
- Frontend uses top-level external imports first, then local imports.
- Do not leave unused imports behind.

## Formatting

- Python in this repo generally uses 4-space indentation.
- Frontend files currently mix quote styles; preserve the dominant style of the file you touch.
- Keep line lengths reasonable even though no formatter is enforced.
- Prefer trailing commas in multiline Python literals and calls when that improves diffs.
- Preserve existing whitespace around JSX and object literals unless you are normalizing the whole file deliberately.

## Types

- Add type hints for new Python functions where practical; the backend already uses typed signatures heavily.
- Use `Optional[...]`, `list[...]`, `dict[...]`, and precise return types rather than leaving new APIs untyped.
- In TypeScript/TSX, prefer concrete interfaces or type aliases for response and state shapes.
- Avoid introducing new `any` usages unless there is no realistic typed alternative.
- Respect `strict: true` in `frontend/tsconfig.app.json`.

## Naming

- Use `snake_case` for Python variables, functions, and module-level helpers.
- Use `PascalCase` for Pydantic models, React components, and TypeScript interfaces.
- Use `UPPER_SNAKE_CASE` for module constants.
- Prefer descriptive helper names like `_build_result_payload` over vague names like `handle_data`.
- Keep route names and payload field names consistent with existing API contracts.

## Error Handling

- In FastAPI routes and request validation helpers, raise `HTTPException` with clear status codes and user-facing messages.
- In lower-level backend helpers, log failures with `logger.error(...)` or `logger.warning(...)` and return safe fallbacks when appropriate.
- Preserve the repo's current pattern of catching broad exceptions only at process boundaries, persistence boundaries, or external API boundaries.
- When re-raising, include actionable context.
- Do not swallow exceptions silently.

## Backend Conventions

- Keep environment/config loading centralized; current code uses `utils.env_loader.load_dotenv_file` and config helpers in `backend.ai_engine`.
- Reuse existing helpers for auth, DB access, and job persistence instead of duplicating logic.
- Prefer `Path` for filesystem paths.
- Keep long-running work out of request handlers; current code uses background threads for processing jobs.
- Update persisted job status consistently when changing pipeline stages.

## Frontend Conventions

- Prefer functional React components and hooks.
- Keep API calls routed through shared helpers such as `authenticatedFetch` when working inside `frontend/src/App.tsx`.
- Preserve existing prop/interface typing patterns.
- Match the existing component naming and UI state naming conventions.
- Avoid introducing a new state library unless the task clearly demands it.

## Validation Expectations For Agents

- After frontend changes, at minimum run `cd frontend && npm run build`.
- After backend changes, at minimum run a backend startup or syntax smoke check.
- After full-stack changes, validate both sides.
- If you cannot run a relevant check, say so explicitly in your handoff.

## Files To Treat Carefully

- `.env`
- `.env.json`
- `outputs/`
- OAuth credentials and API key settings stored by the app

## When Updating This File

- Keep it synchronized with actual repo scripts and configs.
- Prefer facts derived from checked-in files over assumptions.
- Update the commands section whenever a lint or test runner is added.
