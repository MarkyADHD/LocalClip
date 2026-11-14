"use client";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { ToolButton } from "@/components/editor/studio-ui";
import { clipEnd, clipValues, docDuration, setLook, timecode, trackOf } from "@/lib/project/document";
import { Engine } from "./engine";
import type { Project } from "./use-project";

/** The playhead, refreshed about ten times a second: enough for labels, cheap enough for React. */
export function usePlayhead(engine: Engine | null) {
  const snapshot = useRef({ time: 0, playing: false });
  return useSyncExternalStore(
    (notify) => engine?.subscribe(notify) ?? (() => {}),
    () => {
      const time = engine ? Math.round(engine.time * 10) / 10 : 0,
        playing = engine?.playing ?? false;
      if (snapshot.current.time !== time || snapshot.current.playing !== playing) snapshot.current = { time, playing };
      return snapshot.current;
    },
    () => snapshot.current,
  );
}

/** The preview. Drag a selected overlay or text to move it; scroll over it to resize. */
export function Viewer({
  project,
  selected,
  onEngine,
  engine,
}: {
  project: Project;
  selected: ReadonlySet<string>;
  engine: Engine | null;
  onEngine: (engine: Engine | null) => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const doc = project.doc!;
  const { endpoint, update } = project;
  const { time, playing } = usePlayhead(engine);
  const [dragging, setDragging] = useState(false);
  useEffect(() => {
    const created = new Engine(canvas.current!, endpoint);
    onEngine(created);
    return () => {
      onEngine(null);
      created.destroy();
    };
  }, [endpoint, onEngine]);

  // The one selected clip under the playhead that can be moved around the frame.
  const movable = (() => {
    if (selected.size !== 1 || !engine) return null;
    const clip = doc.clips.find((c) => selected.has(c.id));
    if (!clip || trackOf(doc, clip).kind === "audio" || trackOf(doc, clip).locked) return null;
    return clip.start <= engine.time && engine.time < clipEnd(clip) ? clip : null;
  })();
  const drag = useRef<{ x: number; y: number; cx: number; cy: number } | null>(null);
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex min-h-0 flex-1 items-center justify-center bg-black/40 p-3">
        <canvas
          ref={canvas}
          aria-label="Preview"
          data-testid="preview"
          className="max-h-full max-w-full rounded-sm bg-black shadow-lg"
          style={{ aspectRatio: `${doc.width} / ${doc.height}`, cursor: movable ? (dragging ? "grabbing" : "move") : "default", touchAction: "none" }}
          onPointerDown={(event) => {
            if (!movable || !engine) return;
            const v = clipValues(movable, engine.time - movable.start);
            drag.current = { x: event.clientX, y: event.clientY, cx: v.x, cy: v.y };
            event.currentTarget.setPointerCapture(event.pointerId);
            setDragging(true);
          }}
          onPointerMove={(event) => {
            const start = drag.current;
            if (!start || !movable || !engine) return;
            const rect = event.currentTarget.getBoundingClientRect();
            let x = start.cx + (event.clientX - start.x) / rect.width,
              y = start.cy + (event.clientY - start.y) / rect.height;
            // Settle on the centre lines when close.
            if (Math.abs(x - 0.5) < 0.015) x = 0.5;
            if (Math.abs(y - 0.5) < 0.015) y = 0.5;
            const at = engine.time;
            update((d) => setLook(d, movable.id, at, { x, y }), "move-in-frame");
          }}
          onPointerUp={() => {
            drag.current = null;
            setDragging(false);
          }}
          onWheel={(event) => {
            if (!movable || !engine) return;
            const at = engine.time,
              scale = Math.min(10, Math.max(0.05, clipValues(movable, at - movable.start).scale * Math.exp(-event.deltaY * 0.001)));
            update((d) => setLook(d, movable.id, at, { scale }), "scale-in-frame");
          }}
        />
      </div>
      <div className="flex shrink-0 items-center justify-center gap-1 border-t px-3 py-1.5">
        <ToolButton label="Go to start" shortcut="Home" size="icon-sm" onClick={() => engine?.seek(0)}>
          <SkipBack />
        </ToolButton>
        <ToolButton label={playing ? "Pause" : "Play"} shortcut="Space" size="icon-sm" onClick={() => engine?.toggle()}>
          {playing ? <Pause /> : <Play />}
        </ToolButton>
        <ToolButton label="Go to end" shortcut="End" size="icon-sm" onClick={() => engine?.seek(docDuration(doc))}>
          <SkipForward />
        </ToolButton>
        <span className="ml-2 text-xs tabular-nums text-muted-foreground" data-testid="timecode">
          <b className="text-foreground">{timecode(time)}</b> / {timecode(docDuration(doc))}
        </span>
      </div>
    </div>
  );
}
