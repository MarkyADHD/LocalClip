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
