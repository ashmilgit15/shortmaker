# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture Overview

**ShortMaker** is an AI-powered YouTube Shorts generator with a full-stack architecture:

- **Backend**: FastAPI (Python 3.10-3.12) serving REST API + AI processing pipeline
- **Frontend**: React 19 + Vite + TypeScript SPA with Clerk authentication
- **Database**: PostgreSQL (Neon) for job persistence, user tracking, daily quotas
- **AI**: Google Gemini 2.5-flash for highlight detection and virality scoring
- **Video**: yt-dlp for downloads, FFmpeg for processing, Whisper for transcription

### Core Data Flow
1. User submits YouTube URL or uploads video via frontend
2. Backend creates job record, processes asynchronously in a `daemon=True` background thread
3. Pipeline: Download → Transcribe (Groq API first, local Whisper fallback) → AI Highlight Detection → Clip Extraction → Caption Burning
4. Results stored in `outputs/`, metadata persisted to PostgreSQL + file-based JSON in `outputs/jobs/{job_id}.json`
5. Frontend polls `/status/{job_id}` for progress updates
6. Optional webhook callback (`callback_url`) for headless/n8n integration

### Key Backend Modules
| Module | Purpose |
|--------|---------|
| `backend/main.py` | FastAPI app (~2400 lines), all API routes, CORS, auth middleware |
| `backend/ai_engine.py` | Gemini AI integration, config load/save via `.env.json`, virality scoring |
| `backend/video.py` | YouTube downloader (yt-dlp wrapper with cookie + PO token support) |
| `backend/transcription.py` | Whisper speech-to-text (Groq API + local fallback) |
| `backend/highlights.py` | AI + rule-based highlight detection |
| `backend/shorts.py` | Video clip orchestration, FFmpeg filter graphs, 9:16 crop |
| `backend/db.py` | PostgreSQL persistence layer (psycopg); gracefully disabled if no `DATABASE_URL` |
| `backend/clerk_auth.py` | Clerk JWT validation, `ClerkUser` dataclass |
| `backend/trends.py` | Firecrawl-powered trend video discovery |
| `backend/youtube_publish.py` | YouTube Data API upload, OAuth flow |
| `backend/ytdlp_cookie_sync.py` | Automatic browser cookie sync worker for yt-dlp |
| `utils/ffmpeg_helpers.py` | FFmpeg subprocess wrappers |
| `utils/env_loader.py` | Dotenv loading |
| `utils/secret_store.py` | Encrypted secrets via `SHORTMAKER_SECRET_KEY` |

### Important Constants (in `backend/main.py`)
- `ADMIN_ROUTE_PREFIX = "/ashmil2010"` — hidden admin console prefix, bypasses Clerk auth
- `MAX_CLIPS = 10`, `DAILY_PROCESS_LIMIT = 3`, `SHORTS_MAX_DURATION_SECONDS = 59.0`
- `RECENT_JOB_LIMIT = 12`

### Dual Persistence Model
Jobs are persisted two ways simultaneously:
- **File-based**: `outputs/jobs/{job_id}.json` — always available, used as primary read source
- **PostgreSQL**: via `backend/db.py` — used for user quotas, history queries, ownership checks; disabled gracefully when `DATABASE_URL` is not set

On startup, `recover_incomplete_jobs()` marks any in-flight jobs as `error` with reason "Server restarted".

### Authentication Layers
Routes use layered auth decorators — understand which one a route uses before modifying:
- `_require_api_key` — X-API-Key or Bearer token (hashed keys in config)
- `_require_admin_token` — X-Admin-Token header (env var `SHORTMAKER_ADMIN_TOKEN`)
- `_require_app_user` — Clerk JWT validation
- `_require_app_user_or_api_key` — either Clerk JWT or API key (most protected routes)
- `_require_admin_user` — Clerk user in `SHORTMAKER_ADMIN_EMAILS` or `SHORTMAKER_ADMIN_USER_IDS`

### Frontend Architecture
- `frontend/src/App.tsx` — Main app shell with tabs (process/history/trends/settings)
- `frontend/src/main.jsx` — React bootstrap with `<ClerkProvider>` at root
- `frontend/src/types.ts` — TypeScript interfaces for API contracts
- `frontend/src/components/` — UI components
- Vite dev server on `:5173` proxies API prefixes (`/capabilities`, `/session`, `/jobs`, `/process`, `/trends`, `/shorts`, `/youtube`, `/ai`) to `http://127.0.0.1:8000` unless `VITE_API_BASE_URL` is set
- All API calls go through `authenticatedFetch` helper (attaches Clerk bearer token)

## Essential Commands

### Development Setup
```bash
# Backend (preferred with uv)
uv sync

# Frontend
cd frontend && npm install
```

### Running Locally
```bash
# Backend - use scoped reload runner (Windows-safe, watches only backend/ and utils/)
python dev_server.py

# Direct uvicorn (no scoped reload)
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000

# Frontend dev server (port 5173, proxies API to :8000)
cd frontend && npm run dev
```

### Build & Validation
```bash
# Frontend build (TypeScript check + Vite bundle → frontend/dist/)
cd frontend && npm run build

# Backend syntax check
uv run python -m compileall backend utils dev_server.py

# Production Docker build
docker compose up --build -d
```

### API Testing
```bash
curl http://localhost:8000/health
curl http://localhost:8000/capabilities
curl http://localhost:8000/auth/mode
```

## Environment Configuration

### Backend (.env)
```bash
# Required
DATABASE_URL=postgresql://...
CLERK_ISSUER=https://your-domain.clerk.accounts.dev
VITE_CLERK_PUBLISHABLE_KEY=pk_test_...

# Optional
GEMINI_API_KEY=...
GROQ_API_KEY=...
SHORTMAKER_ADMIN_TOKEN=...
SHORTMAKER_AUTH_MODE=production   # default: quick (open when no keys exist)
SHORTMAKER_SECRET_KEY=...        # enables encrypted .env.json
SHORTMAKER_ADMIN_EMAILS=...
SHORTMAKER_ADMIN_USER_IDS=...
```

### Frontend (frontend/.env.local)
```bash
VITE_CLERK_PUBLISHABLE_KEY=pk_test_...
# VITE_API_BASE_URL=http://127.0.0.1:8000  # only if bypassing Vite proxy
```

## Deployment

### Render (Blueprint)
- `render.yaml` defines web service + PostgreSQL
- Set env vars in dashboard — see `.env.production.example` for full list
- Auto-deploy on push to connected repo

### Docker
```bash
cp .env.production.example .env.production
docker compose up --build -d
```

## Important Conventions

### Python Style
- 4-space indentation, `snake_case` for functions/vars
- Type hints required: `Optional[...]`, `list[...]`, `dict[...]`
- Trailing commas in multiline literals for cleaner diffs
- Raise `HTTPException` in routes, `logger.error()` in lower-level helpers

### TypeScript/React
- Functional components with hooks, strict TypeScript (`strict: true`)
- Avoid `any` types; use interfaces from `types.ts` for API shapes
- Route API calls through `authenticatedFetch` helper

### Dev Server Notes
- `dev_server.py` scopes `watchfiles` to `backend/` and `utils/` only — prevents restarts from `.venv/`, `outputs/`, `node_modules/` changes
- Bare `uvicorn --reload` restarts on any file change and kills in-flight jobs; avoid for active processing
- Backend serves `frontend/dist/` as static files in production (SPA catch-all for unrecognized paths)

## Files to Handle Carefully
- `.env`, `.env.json` — environment and encrypted secrets
- `outputs/` — runtime artifacts (jobs, shorts, uploads, temp), not source control
- OAuth credentials, API keys — never commit

## Testing Notes
- No automated test suite currently configured
- Validate frontend changes: `cd frontend && npm run build`
- Validate backend changes: start server or run `uv run python -m compileall backend utils dev_server.py`
- For full-stack changes: validate both sides
