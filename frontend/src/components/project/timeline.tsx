"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Eye,
  EyeOff,
  Lock,
  LockOpen,
  Volume2,
  VolumeX,
} from "lucide-react";
import {
  addAssetClip,
  clipEnd,
  docDuration,
  moveClips,
  timecode,
  trimClip,
  type ProjectDocument,
  type TimedWord,
  type Track,
} from "@/lib/project/document";
import type { Engine } from "./engine";
import type { Project } from "./use-project";

const HEADER = 136;
const RULER = 24;
const HEIGHTS = { video: 56, audio: 42, text: 30, captions: 24 };
const COLORS = {
  video: ["#3b4a8f", "#8ea2ff"],
  image: ["#6b3f8f", "#d3a4ff"],
  audio: ["#1f6b55", "#63e6be"],
  text: ["#8a6a1c", "#ffd666"],
};
export const ASSET_DRAG = "application/x-localclip-asset";

type Row = { key: string; track?: Track; height: number; top: number };
type Drag =
  | { kind: "scrub" }
  | {
      kind: "move" | "start" | "end";
      id: string;
      x: number;
      origin: ProjectDocument;
      ids: Set<string>;
      moved: boolean;
    };

/** Text rows on top, then picture layers highest first, captions, then sound. */
function layout(doc: ProjectDocument): Row[] {
  const of = (kind: Track["kind"]) => doc.tracks.filter((t) => t.kind === kind);
  const rows: Omit<Row, "top">[] = [
    ...of("text").reverse().map((track) => ({ key: track.id, track, height: HEIGHTS.text })),
    ...of("video").reverse().map((track) => ({ key: track.id, track, height: HEIGHTS.video })),
    { key: "captions", height: HEIGHTS.captions },
    ...of("audio").map((track) => ({ key: track.id, track, height: HEIGHTS.audio })),
  ];
  let top = RULER;
  return rows.map((row) => {
    const placed = { ...row, top };
    top += row.height;
    return placed;
  });
}

export function Timeline({
  project,
  engine,
  lines,
  selected,
  onSelect,
  snapping,
  zoom,
  onZoom,
}: {
  project: Project;
  engine: Engine | null;
  lines: TimedWord[][];
  selected: ReadonlySet<string>;
  onSelect: (ids: Set<string>) => void;
  snapping: boolean;
  /** Pixels per second; 0 fits the whole timeline in view. */
  zoom: number;
  onZoom: (zoom: number) => void;
}) {
  const doc = project.doc!;
  const { assets, waves, update, endpoint } = project;
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  const [cursor, setCursor] = useState("default");
  const scroll = useRef(0);
  const drag = useRef<Drag | null>(null);
  const sprites = useRef(new Map<string, HTMLImageElement>());
  const dirty = useRef(true);
  const rows = useMemo(() => layout(doc), [doc]);
  const height = rows[rows.length - 1].top + rows[rows.length - 1].height;
  const total = Math.max(docDuration(doc), 10);
  const fit = (width - 24) / (total * 1.05);
  const pps = zoom || fit;
  const state = useRef({ doc, rows, pps, selected, lines, assets, waves, width, height });
  state.current = { doc, rows, pps, selected, lines, assets, waves, width, height };
  dirty.current = true;

  useEffect(() => {
    const element = wrapRef.current!;
    const observer = new ResizeObserver(() => setWidth(Math.max(200, element.clientWidth - HEADER)));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // One drawing loop: redraws when something changed or the playhead moved.
  useEffect(() => {
    const canvas = canvasRef.current!,
      ctx = canvas.getContext("2d")!;
    let raf = 0,
      drawnTime = -1,
      drawnScroll = -1;
    const sprite = (asset: string) => {
      let image = sprites.current.get(asset);
      if (!image) {
        image = new Image();
        image.onload = () => (dirty.current = true);
        image.src = `${endpoint}/assets/${asset}/thumbs.jpg`;
        sprites.current.set(asset, image);
      }
      return image.complete && image.naturalWidth ? image : null;
    };
    const draw = () => {
      raf = requestAnimationFrame(draw);
      const s = state.current,
        time = engine?.time ?? 0;
      // Keep the playhead in view while playing.
      if (engine?.playing) {
        const x = (time - scroll.current) * s.pps;
        if (x > s.width - 40 || x < 0) scroll.current = Math.max(0, time - 40 / s.pps);
      }
      if (!dirty.current && time === drawnTime && scroll.current === drawnScroll) return;
      dirty.current = false;
      drawnTime = time;
      drawnScroll = scroll.current;
      const ratio = window.devicePixelRatio || 1;
      if (canvas.width !== Math.round(s.width * ratio) || canvas.height !== Math.round(s.height * ratio)) {
        canvas.width = Math.round(s.width * ratio);
        canvas.height = Math.round(s.height * ratio);
      }
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.clearRect(0, 0, s.width, s.height);
      const x = (t: number) => (t - scroll.current) * s.pps;
      const from = scroll.current,
        to = scroll.current + s.width / s.pps;
      // Ruler
      ctx.font = "10px ui-sans-serif, system-ui, sans-serif";
      ctx.textBaseline = "middle";
      const step = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600].find((v) => v * s.pps >= 70) ?? 7200;
      ctx.fillStyle = "#8b8b93";
      ctx.strokeStyle = "#2a2a30";
      for (let t = Math.floor(from / step) * step; t < to; t += step) {
        ctx.fillRect(x(t), RULER - 6, 1, 6);
        ctx.fillText(step < 1 && t % 1 ? `${timecode(t)}.5` : timecode(t), x(t) + 4, 9);
      }
      for (const chapter of s.doc.chapters) {
        ctx.fillStyle = "#f59e0b";
        ctx.fillRect(x(chapter.time), 0, 2, RULER);
        ctx.fillText(chapter.title.slice(0, 24), x(chapter.time) + 5, 18);
      }
      for (const row of s.rows) {
        ctx.fillStyle = row.track?.locked ? "#141417" : "#18181c";
        ctx.fillRect(0, row.top, s.width, row.height - 1);
        if (!row.track) {
          // Captions: one pill per line on screen.
          ctx.font = "10px ui-sans-serif, system-ui, sans-serif";
          for (const line of s.lines) {
            const a = line[0].start,
              b = line[line.length - 1].end;
            if (b < from || a > to) continue;
            const w = Math.max(2, (b - a) * s.pps - 1);
            ctx.fillStyle = s.doc.captions.enabled ? "#3f3f46" : "#26262b";
            ctx.fillRect(x(a), row.top + 3, w, row.height - 7);
            if (w > 40) {
              ctx.save();
              ctx.beginPath();
              ctx.rect(x(a), row.top, w - 4, row.height);
              ctx.clip();
              ctx.fillStyle = "#d4d4d8";
              ctx.fillText(line.map((word) => word.text).join(" "), x(a) + 4, row.top + row.height / 2);
              ctx.restore();
            }
          }
          continue;
        }
        const dim = row.track.hidden || row.track.muted;
        for (const clip of s.doc.clips) {
          if (clip.track !== row.track.id || clipEnd(clip) < from || clip.start > to) continue;
          const asset = clip.asset ? s.assets[clip.asset] : undefined;
          const [fill, line] = COLORS[clip.text ? "text" : asset?.kind === "image" ? "image" : row.track.kind === "audio" ? "audio" : "video"];
          const left = x(clip.start),
            w = Math.max(2, clip.duration * s.pps - 1),
            top = row.top + 2,
            h = row.height - 5;
          ctx.save();
          ctx.beginPath();
          ctx.roundRect(left, top, w, h, 4);
          ctx.clip();
          ctx.globalAlpha = dim ? 0.45 : 1;
          ctx.fillStyle = fill;
          ctx.fillRect(left, top, w, h);
          const a = Math.max(left, 0),
            b = Math.min(left + w, s.width);
          const sourceAt = (px: number) => clip.offset + ((px - left) / s.pps) * clip.speed;
          const thumbs = asset?.kind === "video" && asset.thumbs && sprite(asset.id);
          if (thumbs && asset?.thumbs && h > 40) {
            const tile = asset.thumbs,
              tw = (h * tile.width) / tile.height;
            for (let px = left + Math.floor((a - left) / tw) * tw; px < b; px += tw) {
              const index = Math.min(tile.count - 1, Math.max(0, Math.floor(sourceAt(px + tw / 2) / tile.step)));
              ctx.drawImage(
                thumbs,
                (index % tile.columns) * tile.width,
                Math.floor(index / tile.columns) * tile.height,
                tile.width,
                tile.height,
                px,
                top,
                tw,
                h,
              );
            }
            ctx.fillStyle = "rgba(10,10,14,0.35)";
            ctx.fillRect(left, top, w, h);
          }
          const wave = asset && asset.kind !== "image" && !clip.muted ? s.waves[asset.id] : undefined;
          if (wave) {
            const rate = asset!.waveRate ?? 20,
              band = thumbs ? h * 0.45 : h - 14,
              base = top + h - 1;
            ctx.fillStyle = line;
            ctx.globalAlpha = (dim ? 0.45 : 1) * 0.85;
            for (let px = a; px < b; px += 2) {
              const i0 = Math.floor(sourceAt(px) * rate),
                i1 = Math.max(i0 + 1, Math.floor(sourceAt(px + 2) * rate));
              let peak = 0;
              for (let i = i0; i < i1 && i < wave.length; i += Math.max(1, Math.floor((i1 - i0) / 8))) peak = Math.max(peak, wave[i] ?? 0);
              const bar = Math.max(1, (peak / 255) * band * Math.min(1.5, clip.volume));
              ctx.fillRect(px, base - bar, 1.4, bar);
            }
            ctx.globalAlpha = dim ? 0.45 : 1;
          }
          if (w > 70) {
            ctx.font = "11px ui-sans-serif, system-ui, sans-serif";
            const label = clip.text ? clip.text.content.split("\n")[0] : (asset?.name ?? "Missing file");
            const textWidth = Math.min(ctx.measureText(label).width + 8, w);
            ctx.fillStyle = "rgba(10,10,14,0.6)";
            ctx.fillRect(a, top, textWidth, 15);
            ctx.fillStyle = "#f4f4f5";
            ctx.fillText(label, a + 4, top + 8);
          }
          // Fades show as wedges at either end.
          ctx.fillStyle = "rgba(0,0,0,0.45)";
          for (const [length, edge, dir] of [[clip.fadeIn, left, 1], [clip.fadeOut, left + w, -1]] as const)
            if (length) {
              ctx.beginPath();
              ctx.moveTo(edge, top);
              ctx.lineTo(edge + dir * length * s.pps, top);
              ctx.lineTo(edge, top + h);
              ctx.fill();
            }
          if (clip.keys.length) {
            ctx.fillStyle = "#facc15";
            for (const key of clip.keys) ctx.fillRect(left + key.t * s.pps - 2, top + h - 6, 4, 4);
          }
          ctx.restore();
          if (s.selected.has(clip.id)) {
            ctx.strokeStyle = "#ffffff";
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.roundRect(left + 1, top + 1, w - 2, h - 2, 4);
            ctx.stroke();
            ctx.fillStyle = "#ffffff";
            ctx.fillRect(left + 2, top + h / 2 - 8, 3, 16);
            ctx.fillRect(left + w - 5, top + h / 2 - 8, 3, 16);
          }
        }
      }
      // Playhead
      ctx.fillStyle = "#f97316";
      ctx.fillRect(x(time) - 1, 0, 2, s.height);
      ctx.beginPath();
      ctx.moveTo(x(time) - 6, 0);
      ctx.lineTo(x(time) + 6, 0);
      ctx.lineTo(x(time), 9);
      ctx.fill();
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [engine, endpoint]);

  const locate = useCallback((event: { clientX: number; clientY: number }) => {
    const rect = canvasRef.current!.getBoundingClientRect(),
      s = state.current;
    const px = event.clientX - rect.left,
      py = event.clientY - rect.top;
    const row = s.rows.find((r) => py >= r.top && py < r.top + r.height);
    const time = Math.max(0, scroll.current + px / s.pps);
    const clip = row?.track
      ? s.doc.clips.find((c) => c.track === row.track!.id && time >= c.start && time < clipEnd(c))
      : undefined;
    let edge: "start" | "end" | null = null;
    if (clip && !row!.track!.locked) {
      const grip = Math.min(8, (clip.duration * s.pps) / 4);
      if ((time - clip.start) * s.pps < grip) edge = "start";
      else if ((clipEnd(clip) - time) * s.pps < grip) edge = "end";
    }
    return { px, py, row, time, clip, edge };
  }, []);

  /** Pulls `time` onto a nearby clip edge or the playhead. */
  const snap = useCallback(
    (time: number, origin: ProjectDocument, ignore: ReadonlySet<string>) => {
      if (!snapping) return time;
      const points = [0, engine?.time ?? 0];
      for (const clip of origin.clips) if (!ignore.has(clip.id)) points.push(clip.start, clipEnd(clip));
      const best = points.reduce((a, b) => (Math.abs(b - time) < Math.abs(a - time) ? b : a));
      return Math.abs(best - time) * state.current.pps < 8 ? best : time;
    },
    [engine, snapping],
  );

  const onPointerDown = (event: React.PointerEvent) => {
    if (event.button !== 0) return;
    const hit = locate(event);
    event.currentTarget.setPointerCapture(event.pointerId);
    if (!hit.clip || hit.py < RULER || hit.row?.track?.locked) {
      if (!event.shiftKey && (hit.py < RULER || !hit.clip)) onSelect(new Set());
      drag.current = { kind: "scrub" };
      engine?.seek(hit.time);
      return;
    }
    let ids = new Set(selected);
    if (event.shiftKey) {
      if (ids.has(hit.clip.id)) ids.delete(hit.clip.id);
      else ids.add(hit.clip.id);
    } else if (!ids.has(hit.clip.id)) ids = new Set([hit.clip.id]);
    // Clips cut together (video with its detached sound) move together.
    for (const clip of doc.clips)
      if (clip.link && doc.clips.some((c) => ids.has(c.id) && c.link === clip.link)) ids.add(clip.id);
    onSelect(ids);
    drag.current = { kind: hit.edge ?? "move", id: hit.clip.id, x: event.clientX, origin: doc, ids, moved: false };
  };
  const onPointerMove = (event: React.PointerEvent) => {
    const active = drag.current,
      hit = locate(event);
    if (!active) {
      setCursor(hit.edge ? "ew-resize" : hit.clip && hit.py >= RULER ? "grab" : "default");
      return;
    }
    if (active.kind === "scrub") {
      engine?.seek(hit.time);
      return;
    }
    if (!active.moved && Math.abs(event.clientX - active.x) < 3) return;
    active.moved = true;
    const clip = active.origin.clips.find((c) => c.id === active.id)!;
    if (active.kind === "move") {
      let delta = (event.clientX - active.x) / state.current.pps;
      const start = snap(clip.start + delta, active.origin, active.ids),
        end = snap(clipEnd(clip) + delta, active.origin, active.ids);
      if (start !== clip.start + delta) delta = start - clip.start;
      else if (end !== clipEnd(clip) + delta) delta = end - clipEnd(clip);
      const origin = active.origin,
        target = hit.row?.track?.id;
      update(() => moveClips(origin, active.ids, delta, active.id, target), "drag");
    } else {
      const origin = active.origin,
        edge = active.kind;
      update(() => trimClip(origin, active.id, edge, snap(hit.time, origin, active.ids), assets), "drag");
    }
  };
  const onPointerUp = (event: React.PointerEvent) => {
    const active = drag.current;
    drag.current = null;
    // A plain click on one of several selected clips narrows the selection to it.
    if (active && active.kind !== "scrub" && !active.moved && !event.shiftKey) {
      const ids = new Set([active.id]);
      const clip = doc.clips.find((c) => c.id === active.id);
      for (const other of doc.clips) if (clip?.link && other.link === clip.link) ids.add(other.id);
      onSelect(ids);
    }
  };
  const onWheel = useCallback(
    (event: WheelEvent) => {
      event.preventDefault();
      const s = state.current,
        rect = canvasRef.current!.getBoundingClientRect();
      if (event.ctrlKey || event.metaKey) {
        const px = event.clientX - rect.left,
          at = scroll.current + px / s.pps,
          next = Math.min(400, Math.max(fit, s.pps * Math.exp(-event.deltaY * 0.002)));
        scroll.current = Math.max(0, at - px / next);
        onZoom(next <= fit * 1.001 ? 0 : next);
      } else {
        const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
        scroll.current = Math.max(0, Math.min(total, scroll.current + delta / s.pps));
      }
      dirty.current = true;
    },
    [fit, onZoom, total],
  );
  useEffect(() => {
    const canvas = canvasRef.current!;
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", onWheel);
  }, [onWheel]);
  useEffect(() => {
    if (!zoom) scroll.current = 0;
  }, [zoom]);

  const setTrack = (id: string, patch: Partial<Track>) =>
    update((d) => ({ ...d, tracks: d.tracks.map((t) => (t.id === id ? { ...t, ...patch } : t)) }));

  return (
    <div ref={wrapRef} className="flex min-h-0 select-none overflow-y-auto" data-testid="timeline">
      <div className="shrink-0 border-r bg-card" style={{ width: HEADER, height }}>
        <div style={{ height: RULER }} className="border-b" />
        {rows.map((row) => (
          <div
            key={row.key}
            style={{ height: row.height }}
            className="flex items-center gap-1 border-b px-2 text-xs text-muted-foreground"
          >
            <span className="min-w-0 flex-1 truncate">{row.track ? row.track.name || row.track.id : "Captions"}</span>
            {row.track ? (
              <>
                {row.track.kind !== "text" && (
                  <HeadButton
                    label={row.track.muted ? "Unmute track" : "Mute track"}
                    onClick={() => setTrack(row.track!.id, { muted: !row.track!.muted })}
                  >
                    {row.track.muted ? <VolumeX className="text-destructive" /> : <Volume2 />}
                  </HeadButton>
                )}
                {row.track.kind !== "audio" && (
                  <HeadButton
                    label={row.track.hidden ? "Show track" : "Hide track"}
                    onClick={() => setTrack(row.track!.id, { hidden: !row.track!.hidden })}
                  >
                    {row.track.hidden ? <EyeOff className="text-destructive" /> : <Eye />}
                  </HeadButton>
                )}
                <HeadButton
                  label={row.track.locked ? "Unlock track" : "Lock track"}
                  onClick={() => setTrack(row.track!.id, { locked: !row.track!.locked })}
                >
                  {row.track.locked ? <Lock className="text-amber-400" /> : <LockOpen />}
                </HeadButton>
              </>
            ) : (
              <HeadButton
                label={doc.captions.enabled ? "Hide captions" : "Show captions"}
                onClick={() => update((d) => ({ ...d, captions: { ...d.captions, enabled: !d.captions.enabled } }))}
              >
                {doc.captions.enabled ? <Eye /> : <EyeOff className="text-destructive" />}
              </HeadButton>
            )}
          </div>
        ))}
      </div>
      <canvas
        ref={canvasRef}
        aria-label="Timeline"
        style={{ width, height, cursor, touchAction: "none" }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => (drag.current = null)}
        onDragOver={(event) => {
          if (event.dataTransfer.types.includes(ASSET_DRAG)) event.preventDefault();
        }}
        onDrop={(event) => {
          const asset = assets[event.dataTransfer.getData(ASSET_DRAG)];
          if (!asset || asset.status !== "ready") return;
          event.preventDefault();
          const hit = locate(event);
          update((d) => addAssetClip(d, asset, hit.row?.track?.id, hit.time));
        }}
      />
    </div>
  );
}

function HeadButton({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="rounded p-0.5 hover:bg-accent hover:text-foreground [&_svg]:size-3.5"
    >
      {children}
    </button>
  );
}
