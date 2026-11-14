# Video editor (long-form projects)

`/projects` is a multi-track editor for whole videos: cut by transcript, remove silences and filler
words, add overlays, text, music and captions, then export a normal 16:9 (or any shape) video.

## Where things live

A project is a folder, not a database row: `TEMP_DIR/projects/<id>/`.

- `project.json` name and owner; `document.json` the draft with its revision.
- `assets/<id>/` one folder per imported file: `meta.json`, a light preview copy (`proxy.mp4` or
  `audio.m4a`), `thumbs.jpg`, `waveform.bin`, `transcript.json`. The original file is used where it
  is and never changed.
- `exports/` finished videos and job status files.

## The document

`backend/src/project_document.py` and `frontend/src/lib/project/document.ts` describe the same thing:
tracks (video tracks listed bottom layer first, audio, text), clips placed on them, the cuts made in
each source, corrected words, chapters and the caption style. Every edit in the UI is a pure function
in `document.ts`; keep the two files in step.

Words belong to the source file. Cutting words in the transcript trims or splits the clips that play
them and closes the gap, and records the cut so it can be restored.

## Preview and export

The preview (`components/project/engine.ts`) plays the preview copies on a canvas. The export
(`chunk_command`) builds the same picture with ffmpeg from the original files, one minute at a time,
two at once, then joins the pieces. Finished pieces are named by what they contain, so a failed
export picks up where it stopped. Change the preview and the export together.

## Jobs

`prepare_asset`, `transcribe_asset` and `export_project` run in the ARQ worker
(`services/project_service.py`). Routes are in `api/routes/projects.py`.

## Assistant and MCP

The AI tab sends the timeline's transcript and the request to the model picked in Settings
(`project_ai.py`, `POST /projects/{id}/assistant`). The answer is a list of proposed edits (cuts,
chapters, title, description, on-screen text). Nothing is changed on the server: the editor shows
the edits, and applies the ones the user keeps with `applyEdits` as one undoable change. Cuts are
stored as source ranges, so they still hit the right words if the timeline moved meanwhile.

On a self-hosted install the backend is also an MCP server (`mcp_server.py`):

    claude mcp add --transport http localclip http://localhost:8000/mcp/

Its tools read projects, transcripts and timelines, start exports, and `propose_edits`, which leaves
edits in the project's `proposals.json` for the AI tab to show. The editor checks for them every few
seconds.
