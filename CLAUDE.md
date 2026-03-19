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
2. Backend creates job record, processes asynchronously (background threads)
3. Pipeline: Download → Transcribe → AI Highlight Detection → Clip Extraction → Caption Burning
4. Results stored in `outputs/`, metadata persisted to PostgreSQL
5. Frontend polls `/status/{job_id}` for progress updates

### Key Backend Modules
| Module | Purpose |
|--------|---------|
| `backend/main.py` | FastAPI app, API routes, CORS, auth middleware |
| `backend/ai_engine.py` | Gemini AI integration, prompt construction, virality scoring |
| `backend/video.py` | YouTube downloader (yt-dlp wrapper) |
| `backend/transcription.py` | Whisper speech-to-text (Groq API + local fallback) |
| `backend/highlights.py` | AI + rule-based highlight detection |
| `backend/shorts.py` | Video clip orchestration, FFmpeg filter graphs |
| `backend/db.py` | PostgreSQL persistence layer (psycopg) |
| `backend/clerk_auth.py` | Clerk JWT validation |

### Frontend Structure
- `frontend/src/App.tsx` - Main app shell with tabs (process/history/trends/settings)
- `frontend/src/main.jsx` - React bootstrap + ClerkProvider
- `frontend/src/components/` - UI components (LandingPage, Sidebar, ProcessView, etc.)
- `frontend/src/types.ts` - TypeScript interfaces for API contracts

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
# Backend - use scoped reload runner (Windows)
python dev_server.py

# Direct uvicorn
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000

# Frontend dev server
cd frontend && npm run dev
```

### Build & Validation
```bash
# Frontend build (TypeScript check + Vite)
cd frontend && npm run build

# Backend syntax check
uv run python -m compileall backend utils dev_server.py

# Production Docker build
docker compose up --build -d
```

### API Testing
```bash
# Health check
curl http://localhost:8000/health

# Get capabilities
curl http://localhost:8000/capabilities

# Check auth mode
curl http://localhost:8000/auth/mode
```

## Authentication & API Keys

### Clerk (Frontend Auth)
- Frontend uses `@clerk/react` with `<ClerkProvider>`
- Backend validates JWT via `backend/clerk_auth.py`
- Configure `VITE_CLERK_PUBLISHABLE_KEY` in `frontend/.env.local`

### API Keys (Automation)
- Create keys via `POST /api-keys` (requires `X-Admin-Token`)
- Send `X-API-Key` or `Authorization: Bearer` header for protected endpoints
- Protected: `/process/*`, `/status/*`, `/result/*`, `/shorts/*`
- Mode control: `GET/POST /auth/mode` (quick vs production)

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
SHORTMAKER_AUTH_MODE=production
```

### Secrets Management
- Runtime secrets encrypted in `.env.json` when `SHORTMAKER_SECRET_KEY` is set
- Never commit `.env`, `.env.json`, or credentials
- Treat `outputs/` as ephemeral runtime state

## Deployment

### Render (Blueprint)
- `render.yaml` defines web service + PostgreSQL
- Set env vars in dashboard: `DATABASE_URL`, `CLERK_ISSUER`, secrets
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
- Raise `HTTPException` in routes, log in lower-level helpers

### TypeScript/React
- Functional components with hooks
- Strict TypeScript (`strict: true`)
- Avoid `any` types; use interfaces for API shapes
- Route API calls through `authenticatedFetch` helper

### Error Handling
- FastAPI routes: `HTTPException` with status codes + user messages
- Lower-level: `logger.error()` + safe fallbacks
- Never swallow exceptions silently

## Files to Handle Carefully
- `.env`, `.env.json` - environment and secrets
- `outputs/` - runtime artifacts, not source control
- OAuth credentials, API keys - never commit

## Testing Notes
- No automated test suite currently configured
- Validate frontend changes: `cd frontend && npm run build`
- Validate backend changes: start server or run syntax check
- For full-stack changes: validate both sides
