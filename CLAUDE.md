# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project Overview

LocalClip is a Windows-native AI clipping tool for Twitch/YouTube streamers. It turns long
VODs into short vertical clips on the user's own PC: no Docker, no cloud services required.
AGPL-3.0 licensed.

## Running it

`LocalClip.cmd` / `LocalClip.ps1` is the launcher (`Close LocalClip.*` stops it, `install.ps1`
does first-time setup). It:

- downloads portable PostgreSQL (port 5433) and Redis for Windows (port 6380) into a tools folder,
  initialises the database from `init.sql` on first run;
- runs `uv sync --extra cuda` and `pnpm install && pnpm run build` when `HEAD` changes;
- starts, as hidden processes with logs in the state folder:
  - backend: `uv run uvicorn src.main:app --port 8000`
  - worker: `uv run arq src.workers.tasks.WorkerSettings`
  - frontend: `next start -p 3107`
- opens http://localhost:3107.

`docker-compose.yml` still exists for development on other platforms.

### Backend (dev)

Uses `uv`. Python 3.11+, ffmpeg, PostgreSQL and Redis must be running.

```bash
cd backend
uv sync
uv run uvicorn src.main:app --reload --port 8000
uv run arq src.workers.tasks.WorkerSettings
.venv/bin/python -m pytest tests/unit -q          # unit tests
```

### Frontend (dev)

```bash
cd frontend
pnpm install
pnpm run dev
npx tsc --noEmit && pnpm -s lint && pnpm -s vitest run
```

## Architecture

```
Browser → Next.js 15 frontend (:3107) → FastAPI backend (:8000) → Redis queue → ARQ worker
                                              ↓                                   ↓
                                         PostgreSQL ←─────────────────────────────┘
```

Task creation returns immediately; processing runs in the worker; progress goes Redis pub/sub → SSE.
Task status flow: `queued → processing → completed/error/cancelled`.

### Backend layout (`backend/src/`)

- `api/routes/` HTTP handlers (`tasks.py`, `media.py`, `editor.py`, ...)
- `services/` business logic (`task_service.py`, `video_service.py`)
- `repositories/` raw SQL via `text()` queries, not the ORM
- `workers/` ARQ jobs, queue and progress
- `media/` transcription, captions, timeline, reframing, ffmpeg helpers, stream templates
- `ai.py` clip selection agents; `twitch.py` Twitch VODs and chat; `config.py` env config

Blocking work (ffmpeg, downloads, transcription) is wrapped in `run_in_thread()`.

### Pipeline

1. **Input**: Twitch VOD / YouTube URL (yt-dlp) or uploaded file.
2. **Transcription**: Whisper running locally on the GPU (`WHISPER_MODEL`).
3. **Twitch chat signals**: for Twitch VODs, `twitch.py` downloads the chat replay and scores
   activity spikes, which feed the clip selection as an extra signal.
4. **AI analysis**: the LLM picks segments with virality scores. Default LLM is the Claude Code
   CLI (`LLM=claude-code:sonnet`, provider `claude-code` in `ai.py`); it uses the user's local
   `claude` login. Other providers (`google-gla`, `openai`, `anthropic`, `ollama`, `openrouter`)
   still work. Long transcripts are analysed in windows and reranked.
5. **Rendering**: 9:16 clips with face-tracked crops or a stream template, word-synced
   captions, hook title, optional transitions/B-roll.

### Stream templates

`backend/src/media/stream_layouts.py` finds the facecam once per clip and builds a fixed layout:
`facecam_top`, `gameplay_top`, `floating_cam`, `gameplay_only`. The default (no template) tracks
the biggest face.

### Clip editing

Trim, split, merge, captions, export presets, plus
`POST /tasks/{id}/clips/{clip_id}/extend` with `{"before": s, "after": s}` which re-renders the
clip from the source with extra time (the UI's "+30s" buttons; max 600s each side).

### Frontend

Next.js 15 App Router, React 19, Tailwind v4, shadcn/ui, Better Auth (Prisma). Prisma client is
generated to `frontend/src/generated/prisma/`. In native mode a local session is used, so there is
no sign-up.

### Database

PostgreSQL, schema in `init.sql` (plus `backend/src/migrations/sql/`). `tasks`, `sources`,
`generated_clips` are snake_case; Better Auth tables are camelCase. UUIDs are VARCHAR(36).
The database name, user and password are fixed by `LocalClip.ps1` (`$dbUrl`); keep other
configs in sync with it rather than renaming them.

## Conventions

- Output is 9:16, H.264, even dimensions (`round_to_even()`).
- Fonts: drop `.ttf` into `backend/fonts/`; transitions: `.mp4` into `backend/transitions/`.
- Clip selection prompt: `backend/src/ai.py`.

### Desktop app

`desktop/` is a small Rust (tao + wry/WebView2) app, `LocalClip.exe`. It runs `LocalClip.ps1 -NoBrowser`
hidden, shows http://localhost:3107 in its window, runs `Close LocalClip.ps1` when the window closes, and
shows an update banner when a newer GitHub release than its `Cargo.toml` version exists. To release: bump
`desktop/Cargo.toml`'s version, merge, then run the "Desktop app" workflow by hand; it builds the exe and
creates the `v<version>` release.
