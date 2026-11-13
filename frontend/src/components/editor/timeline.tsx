"use client";
import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Copy,
  Scissors,
  Trash2,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  clamp,
  editDuration,
  mappedWords,
  outputTime,
  sourceTime,
  splitSegment,
  timecode,
  uid,
  type EditDocument,
  type EditorState,
} from "@/lib/editor/document";
import { ToolButton } from "./studio-ui";

interface Props {
  doc: EditDocument;
  asset: EditorState;
  endpoint: string;
  currentTime: number;
  index: number;
  select: (index: number) => void;
  seek: (time: number) => void;
  update: (change: (doc: EditDocument) => EditDocument, group?: string) => void;
}

const NUMBER_INPUT =
  "h-7 w-[4.5rem] rounded-md border bg-transparent px-2 text-xs tabular-nums outline-none [appearance:textfield] focus:border-ring focus:ring-[3px] focus:ring-ring/50 [&::-webkit-inner-spin-button]:appearance-none";

/** Ruler step that keeps roughly ten labels on screen. */
const tickStep = (seconds: number) =>
  [0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300].find(
    (step) => seconds / step <= 12,
  ) ?? 600;

export function Timeline({
  doc,
  asset,
  endpoint,
  currentTime,
  index,
  select,
  seek,
  update,
}: Props) {
  const [zoom, setZoom] = useState(1);
  // While a trim handle is held the scale stays put, so the edge follows the pointer.
  const [frozen, setFrozen] = useState<number | null>(null);
  const scroller = useRef<HTMLDivElement>(null),
    track = useRef<HTMLDivElement>(null);
  const drag = useRef<{
    edge: "start" | "end";
    x: number;
    start: number;
    end: number;
    perSecond: number;
  } | null>(null);
  const active = doc.segments[index] ?? doc.segments[0];
  const total = editDuration(doc),
    scale = frozen ?? total,
    playhead = clamp(outputTime(doc, index, currentTime), 0, total);
  const percent = (seconds: number) => `${(seconds / scale) * 100}%`;
  const setRange = (start: number, end: number) =>
    update(
      (d) => ({
        ...d,
        segments: d.segments.map((s) =>
          s.id === active.id
            ? {
                ...s,
                start: clamp(start, 0, end - 0.04),
                end: clamp(end, start + 0.04, asset.duration),
              }
            : s,
        ),
      }),
      "trim",
    );
  const move = (direction: number) => {
    const target = index + direction;
    if (target < 0 || target >= doc.segments.length) return;
    update((d) => {
      const segments = [...d.segments];
      [segments[index], segments[target]] = [segments[target], segments[index]];
      return { ...d, segments };
    });
    select(target);
  };
  const scrub = (clientX: number) => {
    const box = track.current!.getBoundingClientRect();
    const at = sourceTime(
      doc,
      clamp((clientX - box.left) / box.width, 0, 1) * scale,
    );
    select(at.index);
    seek(at.time);
  };
  const canSplit =
    currentTime > active.start + 0.04 && currentTime < active.end - 0.04;
  // Keep the playhead in view when the timeline is zoomed in.
  useEffect(() => {
    const view = scroller.current;
    if (!view || view.scrollWidth <= view.clientWidth) return;
    const x = (playhead / scale) * view.scrollWidth;
    if (x < view.scrollLeft + 24 || x > view.scrollLeft + view.clientWidth - 24)
      view.scrollLeft = x - view.clientWidth / 3;
  }, [playhead, scale, zoom]);
  const step = tickStep(scale / zoom);
  const words = mappedWords(doc);
  return (
    <section
      aria-label="Clip timeline"
      className="shrink-0 border-t bg-card text-card-foreground"
    >
      <div className="flex flex-wrap items-center gap-x-1 gap-y-2 border-b px-3 py-1.5">
        <Button
          size="sm"
          variant="secondary"
          className="h-7"
          onClick={() => update((d) => splitSegment(d, index, currentTime))}
          disabled={!canSplit}
          aria-label="Split at playhead"
          title="Split at playhead (S)"
        >
          <Scissors />
          Split
        </Button>
        <ToolButton
          label="Remove selected segment"
          shortcut="Del"
          size="icon-sm"
          className="hover:text-destructive"
          disabled={doc.segments.length === 1}
          onClick={() => {
            update((d) => ({
              ...d,
              segments: d.segments.filter((s) => s.id !== active.id),
            }));
            select(Math.max(0, index - 1));
          }}
        >
          <Trash2 />
        </ToolButton>
        <ToolButton
          label="Duplicate selected segment"
          size="icon-sm"
          onClick={() =>
            update((d) => ({
              ...d,
              segments: [
                ...d.segments.slice(0, index + 1),
                { ...active, id: uid() },
                ...d.segments.slice(index + 1),
              ],
            }))
          }
        >
          <Copy />
        </ToolButton>
        <ToolButton
          label="Move segment earlier"
          size="icon-sm"
          disabled={index === 0}
          onClick={() => move(-1)}
        >
          <ArrowLeft />
        </ToolButton>
        <ToolButton
          label="Move segment later"
          size="icon-sm"
          disabled={index >= doc.segments.length - 1}
          onClick={() => move(1)}
        >
          <ArrowRight />
        </ToolButton>
        <label className="ml-2 flex items-center gap-1.5 text-xs text-muted-foreground">
          In
          <input
            className={NUMBER_INPUT}
            aria-label="In point seconds"
            type="number"
            min={0}
            max={active.end - 0.04}
            step="0.01"
            value={Number(active.start.toFixed(2))}
            onChange={(e) => setRange(Number(e.target.value), active.end)}
          />
        </label>
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          Out
          <input
            className={NUMBER_INPUT}
            aria-label="Out point seconds"
            type="number"
            min={active.start + 0.04}
            max={asset.duration}
            step="0.01"
            value={Number(active.end.toFixed(2))}
            onChange={(e) => setRange(active.start, Number(e.target.value))}
          />
        </label>
        <span className="ml-auto text-xs tabular-nums text-muted-foreground">
          <span className="font-medium text-foreground">
            {timecode(playhead)}
          </span>{" "}
          / {timecode(total)}
        </span>
        <div className="ml-2 flex items-center gap-1 text-muted-foreground">
          <ZoomOut className="size-3.5" aria-hidden />
          <input
            type="range"
            aria-label="Timeline zoom"
            className="w-20 accent-current"
            min={1}
            max={8}
            step={0.25}
            value={zoom}
            onChange={(e) => setZoom(Number(e.target.value))}
          />
          <ZoomIn className="size-3.5" aria-hidden />
        </div>
      </div>
      <div ref={scroller} className="overflow-x-auto px-3 pt-1 pb-3">
        <div
          ref={track}
          className="relative cursor-pointer touch-none select-none"
          style={{ width: `${zoom * 100}%` }}
          onPointerDown={(e) => {
            if ((e.target as HTMLElement).closest('[role="slider"]')) return;
            e.currentTarget.setPointerCapture(e.pointerId);
            scrub(e.clientX);
          }}
          onPointerMove={(e) => {
            if (e.currentTarget.hasPointerCapture(e.pointerId) && !drag.current)
              scrub(e.clientX);
          }}
        >
          <div className="relative h-5 text-[10px] tabular-nums text-muted-foreground">
            {Array.from({ length: Math.floor(scale / step) + 1 }, (_, i) => (
              <span
                key={i}
                className="absolute top-0 border-l border-border pl-1 leading-5"
                style={{ left: percent(i * step) }}
              >
                {timecode(i * step).replace(/\.00$/, "")}
              </span>
            ))}
          </div>
          <div className="relative flex h-16" role="group" aria-label="Segments">
            {doc.segments.map((s, i) => {
              const length = s.end - s.start,
                selected = i === index,
                samples = asset.waveform.slice(
                  Math.floor((s.start / asset.duration) * asset.waveform.length),
                  Math.max(
                    1,
                    Math.ceil((s.end / asset.duration) * asset.waveform.length),
                  ),
                );
              const handle = (edge: "start" | "end") => (
                <div
                  role="slider"
                  tabIndex={0}
                  aria-label={edge === "start" ? "Trim start" : "Trim end"}
                  aria-valuemin={0}
                  aria-valuemax={Number(asset.duration.toFixed(2))}
                  aria-valuenow={Number(s[edge].toFixed(2))}
                  className={cn(
                    "absolute inset-y-0 z-10 flex w-3 cursor-ew-resize items-center justify-center bg-brand outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    edge === "start"
                      ? "left-0 rounded-l-md"
                      : "right-0 rounded-r-md",
                  )}
                  onKeyDown={(e) => {
                    const direction =
                      e.key === "ArrowLeft" ? -1 : e.key === "ArrowRight" ? 1 : 0;
                    if (!direction) return;
                    e.preventDefault();
                    e.stopPropagation();
                    const delta = direction / asset.fps;
                    if (edge === "start") setRange(s.start + delta, s.end);
                    else setRange(s.start, s.end + delta);
                  }}
                  onPointerDown={(e) => {
                    e.stopPropagation();
                    e.currentTarget.setPointerCapture(e.pointerId);
                    drag.current = {
                      edge,
                      x: e.clientX,
                      start: s.start,
                      end: s.end,
                      perSecond:
                        track.current!.getBoundingClientRect().width / scale,
                    };
                    setFrozen(scale);
                  }}
                  onPointerMove={(e) => {
                    const d = drag.current;
                    if (!d) return;
                    const delta = (e.clientX - d.x) / d.perSecond;
                    if (d.edge === "start") {
                      const start = clamp(d.start + delta, 0, d.end - 0.04);
                      setRange(start, d.end);
                      seek(start);
                    } else {
                      const end = clamp(
                        d.end + delta,
                        d.start + 0.04,
                        asset.duration,
                      );
                      setRange(d.start, end);
                      seek(Math.max(d.start, end - 1 / asset.fps));
                    }
                  }}
                  onPointerUp={() => {
                    drag.current = null;
                    setFrozen(null);
                  }}
                  onPointerCancel={() => {
                    drag.current = null;
                    setFrozen(null);
                  }}
                >
                  <span className="h-5 w-0.5 rounded-full bg-brand-foreground/70" />
                </div>
              );
              return (
                <div
                  key={s.id}
                  aria-current={selected}
                  className={cn(
                    "relative h-full shrink-0 overflow-hidden rounded-md bg-stone-800 ring-1 ring-inset ring-black/60",
                    selected && "ring-2 ring-brand",
                  )}
                  style={{ width: percent(length) }}
                >
                  <div
                    aria-hidden
                    className={cn(
                      "absolute inset-0 opacity-60",
                      selected && "opacity-90",
                    )}
                    style={{
                      backgroundImage: `url(${endpoint}/media/thumbnails.jpg)`,
                      backgroundSize: `${(asset.duration / length) * 100}% 100%`,
                      backgroundPosition: `${asset.duration > length ? (s.start / (asset.duration - length)) * 100 : 0}% 0`,
                    }}
                  />
                  <svg
                    aria-hidden
                    className="absolute inset-x-0 bottom-0 h-7 w-full text-white/80"
                    viewBox={`0 0 ${samples.length} 40`}
                    preserveAspectRatio="none"
                  >
                    <rect width="100%" height="40" fill="black" opacity=".45" />
                    {samples.map((v, n) => (
                      <rect
                        key={n}
                        x={n + 0.15}
                        y={20 - Math.max(1, v * 19)}
                        width="0.7"
                        height={Math.max(2, v * 38)}
                        fill="currentColor"
                      />
                    ))}
                  </svg>
                  <span className="absolute top-1 left-4 rounded bg-black/60 px-1 text-[10px] font-medium text-white">
                    Segment {i + 1}
                  </span>
                  {selected && handle("start")}
                  {selected && handle("end")}
                </div>
              );
            })}
          </div>
          <div aria-hidden className="relative mt-1 h-5">
            {words.map((w, n) => (
              <span
                key={n}
                className={cn(
                  "absolute inset-y-0 truncate rounded-sm bg-muted px-1 text-[10px] leading-5 text-muted-foreground",
                  w.highlight && "bg-brand-soft text-foreground",
                  w.bleep && "bg-red-500/30 text-red-200",
                )}
                style={{
                  left: percent(w.start),
                  width: `max(2px, calc(${percent(w.end - w.start)} - 1px))`,
                }}
              >
                {w.text}
              </span>
            ))}
          </div>
          <div
            aria-hidden
            className="pointer-events-none absolute inset-y-0 z-20 w-px bg-white"
            style={{ left: percent(playhead) }}
          >
            <div className="-ml-[5px] h-2.5 w-[11px] rounded-b-sm bg-white" />
          </div>
        </div>
        <label className="sr-only" htmlFor="studio-playhead">
          Playhead
        </label>
        <input
          id="studio-playhead"
          className="sr-only focus:not-sr-only focus:w-full"
          type="range"
          min={0}
          max={asset.duration}
          step={1 / asset.fps}
          value={currentTime}
          onChange={(e) => seek(Number(e.target.value))}
        />
      </div>
    </section>
  );
}
