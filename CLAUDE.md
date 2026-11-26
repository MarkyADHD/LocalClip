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
- runs `uv sync` on every start, and `pnpm install && pnpm run build` when `HEAD` changes;
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

1. **Input**: Twitch or Kick VOD or clip (`twitch.py`, yt-dlp; cached in the state folder until the
   generation is deleted, the "Delete full video" button is used, or `SOURCE_KEEP_DAYS` (3) pass), YouTube URL, or uploaded file.
2. **Transcription**: faster-whisper (CTranslate2, fp16 on the GPU, VAD on) locally (`WHISPER_MODEL`).
   No torch; cuBLAS/cuDNN come from the `nvidia-*` wheels. Close games while clipping: they share the GPU.
   "My Twitch VODs" on the home screen logs in with Twitch's device code flow (`TWITCH_CLIENT_ID`, a public app, no
   secret; tokens in `TEMP_DIR/twitch_login.json`) and lists the user's videos from Helix (`/tasks/twitch/*`); picking
   one just fills in its link.
3. **Twitch chat signals**: for Twitch VODs, `twitch.py` downloads the chat replay and scores
   activity spikes, which feed the clip selection as an extra signal. `media/reactions.py` tags laughing and
   screaming in the audio (sherpa-onnx CED-tiny, 2 s chunks, ~15 s per stream hour, model downloaded once to
   `TEMP_DIR/models/reactions`); those hints sit beside the loud spikes in `build_clip_signal_summary`.
4. **AI analysis**: the LLM picks segments with virality scores; the prompts target stream
   moments (fails, clutches, reactions, chat spikes), not tutorials or talk. Default LLM is the Claude Code
   CLI (`LLM=claude-code:sonnet`, provider `claude-code` in `ai.py`); it uses the user's local
   `claude` login. Other providers (`google-gla`, `openai`, `anthropic`, `ollama`, `openrouter`)
   still work, plus `local:<model>` for any OpenAI-compatible server at `LOCAL_LLM_BASE_URL` (LM Studio,
   llama.cpp, Jan, ...). Settings > AI model lists every model `local_models.py` finds on the PC
   (`GET/PUT /admin/llm`); Ollama and LM Studio servers are started when a model needs them.
   Long transcripts are analysed in windows and reranked; a score-4 chat or laugh/scream signal no pick covers
   becomes a candidate for the rerank (`add_signal_candidates`, up to 2 per stream hour). The rerank also gets the
   streamer's last 10 posted/exported and 10 deleted clips as taste examples (`taste.py`, `TEMP_DIR/clip_taste.json`). One short line left at either end of a pick 20+ s
   from the rest is dropped (`_trim_dead_air`) when the rest is still 15 s; everything else stays, since the render cuts long pauses.
   Clips are 15-90 s with no target length. A moment whose setup and payoff are further apart (up to 5 min) comes back
   with `keep` parts (at most 90 s in total; `_ground_keep_parts` snaps them to lines and drops middle parts first when
   over); they reach the render as the segment's `source_ranges`, so the gaps are cut out.
5. **Speakers**: `media/diarization.py` (sherpa-onnx on the CPU, models downloaded once to
   `TEMP_DIR/models/speakers`) labels each clip's words by speaker when its captions are built and
   when the editor opens it; speakers after the first get their own caption colour
   (`SPEAKER_CAPTIONS=false` turns it off). Per clip, not per VOD: speaker 0 is whoever talks most.
   Separately, `media/streamer_voice.py` marks each transcript line the clip picker reads as `Speaker Streamer:` or
   `Speaker Other:` (game dialogue, friends): the most common voice in the VOD is the streamer (`STREAMER_VOICE=false`).
6. **Rendering**: 9:16 clips at the source's frame rate (up to 60 fps) with face-tracked crops or a stream template, word-synced
   captions, hook title, optional transitions/B-roll. One near-lossless cut (`INTERMEDIATE_CRF` 8), then one final encode (`FINAL_VIDEO_CRF` 17); Twitch/Kick VODs download at Source quality. Two clips render at once; encodes use
   NVENC when ffmpeg has it (`VIDEO_ENCODER=cpu` forces libx264) and fall back to the CPU on failure.
   Every clip gets one fixed volume to -14 LUFS with a limiter (no noise removal, at Marky's request) and a snap zoom on its loudest
   moment (`AUTO_PUNCH=false`).
   **Auto-blur** (`media/auto_blur.py`, Settings > Auto-blur, on by default, `AUTO_BLUR=false`): each clip's cut is scanned on the CPU
   (onnxruntime) by NudeNet 320n for nudity (4 times a second) and OWLv2 for a vape around the facecam (once a second); sightings are linked into
   tracks and only those boxes are blurred, until the thing is gone. Models download once from the `blur-models-1` pre-release
   (built by `.github/workflows/blur-model.yml`). The editor gets the blurs in the draft (`blurs`) instead, so a wrong one can be removed.

### Stream templates

`backend/src/media/stream_layouts.py` finds the facecam once per clip and builds a fixed layout:
`facecam_top`, `gameplay_top`, `floating_cam`, `gameplay_only`. The default (no template) tracks
the biggest face.

### Clip editing

The studio (`frontend/src/components/editor/`, `/tasks/[id]/edit`) edits a draft document
(`editor_document.py` / `lib/editor/document.ts`: cuts, words, caption style, layout, title). The
preview draws it on a canvas (`lib/editor/render.ts`); the export (always on the PC) builds
the same picture with ffmpeg + libass (`layout_filter`, `write_ass`). Change both together. See `docs/editor.md`.

Caption looks: the editor's one-click `PRESETS` (`inspector.tsx`) are also generation templates (`_look` rows in
`caption_templates.py`, same values, checked by `tests/unit/test_caption_looks.py`), so a clip made with a look opens in the
editor with that look picked. Add a look in both places.

Export-only extras (not in the preview): punch-in zooms, slow motion and replays, mic cleanup, voice/game volume
split (`media/stems.py`) and AI facecam upscaling (`media/upscale.py`, optional download).

"Find more clips" on a finished generation (`POST /tasks/{id}/find-more`, `process_task(find_more=True)`) runs the
AI search again with the ranges already clipped excluded (`exclude_ranges`; kept in the task's
`source_metadata.excluded_ranges` so deleted clips stay excluded) and appends the new clips. A deleted Twitch/Kick/YouTube
source is downloaded again; a failed search leaves the task completed with the reason as its progress message.

"What clips do you want?" (home screen and the Find more popover) saves `source_metadata.clip_request`; the window prompts and
the rerank get it (`_clip_request_note` in `ai.py`), and a run with a request never reads or writes the cached analysis.

"Search the stream" on a finished generation (`components/transcript-search.tsx`): `GET /tasks/{id}/transcript/search?q=` finds a
phrase in the transcript kept in the cache (`search_transcript` in `ai.py`), and `POST /tasks/{id}/clips/from-range` with
`{"start": s, "end": s}` runs the Find more path with `source_metadata.manual_range` set, which clips that range and skips the AI.

Trim, split, merge, captions, export presets, plus
`POST /tasks/{id}/clips/{clip_id}/extend` with `{"before": s, "after": s}` which re-renders the
clip from the source with extra time (the UI's "+30s" buttons; max 600s each side).

### Posting

"Post" on a finished clip (`components/post-clip.tsx`, `api/routes/post.py`): a button each for YouTube, TikTok and Instagram copies the
caption, shows the file in Explorer and opens the upload page. "Write with AI" (`post_captions.py`, `POST /tasks/{id}/clips/{clip_id}/captions`) writes a caption with hashtags per site from the clip's transcript with the Settings > AI model. LocalClip uploads nothing itself (a YouTube login was built and removed at
Marky's request). See `docs/posting.md`.
For a Twitch VOD's clips, "Clip on Twitch" (`POST /tasks/{id}/clips/{clip_id}/twitch-clip`, `create_vod_clip` in `twitch.py`) makes
the same moment a real Twitch clip with Helix "Create Clip From VOD" (open beta; at most 60 s, so a longer clip becomes its
first minute). It uses the "Log in with Twitch" login, which asks for `channel:manage:clips editor:manage:clips`; a login from
before that is asked to log in again.
Tick boxes on the results page plus "Export all" (`components/batch-export.tsx`) copy the ticked clips to
`Videos\LocalClip\<stream title>\` (`POST /tasks/{id}/clips/{clip_id}/export-to-folder`) and open that folder.

### Video editor

`/projects` (`frontend/src/components/project/`, `backend/src/project_document.py`,
`services/project_service.py`, `api/routes/projects.py`) is a multi-track editor for whole videos.
Projects are folders under `TEMP_DIR/projects/`; the canvas preview and the chunked ffmpeg export must
draw the same picture. See `docs/video-editor.md`.

### Frontend

Next.js 15 App Router, React 19, Tailwind v4, shadcn/ui, Better Auth (Prisma). Prisma client is
generated to `frontend/src/generated/prisma/`. In native mode a local session is used, so there is
no sign-up. The app is dark by default (`class="dark"` on `<html>`); Settings > Appearance stores
`localclip-theme` in localStorage. Use theme tokens (`bg-card`, `text-muted-foreground`, `text-destructive`), not `gray-*`/`white`.

### User counter

`backend/src/usage_count.py`: on by default (Marky's call), off switch in Settings > Privacy (`GET/PUT /admin/usage-count`).
The native app hits a public Abacus counter once per install and once per month, with no ID. Keep the README privacy policy
accurate about exactly what is sent.

### Problem reports

`LocalClip.ps1` moves the last run's logs to `.localclip/logs/old/<time>` (5 runs kept). Settings > Help > "Report a problem"
(`backend/src/problem_report.py`, `GET /admin/problem-report`) shows the PC's details and log ends for the user to paste into a
GitHub issue. The app never sends it; keep it that way (README privacy policy).

### Setup check

`backend/src/setup_check.py` (`GET /admin/setup-check`) lists what stops this PC from making clips (no AI model, no ffmpeg) or
slows it down (no NVIDIA card, low disk). The home screen shows the list (`components/setup-check.tsx`); warnings can be hidden.

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
installs a newer GitHub release than its `Cargo.toml` version before starting (silent `LocalClip-Setup.exe`, then reopens). To release: bump
`desktop/Cargo.toml`'s version, merge, then run the "Desktop app" workflow by hand; it builds the exe and
creates the `v<version>` release with `LocalClip-Setup.exe` (Inno Setup, `desktop/setup.iss`).
