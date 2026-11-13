"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Pause,
  Play,
  SkipBack,
  SkipForward,
  Repeat,
  VolumeX,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Toggle } from "@/components/ui/toggle";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

/** Rough share of a 9:16 frame each app covers with its own UI (they shift between app versions). */
const SAFE_ZONES = {
  tiktok: { label: "TikTok", top: 7, bottom: 19, right: 12 },
  reels: { label: "Reels", top: 11, bottom: 21, right: 12 },
  shorts: { label: "Shorts", top: 14, bottom: 20, right: 13 },
} as const;
type SafeZone = keyof typeof SAFE_ZONES | "off";
import {
  clamp,
  frameRect,
  outputSize,
  outputTime,
  type EditDocument,
  type EditorState,
} from "@/lib/editor/document";
import { drawEditorFrame, loadEditorFont } from "@/lib/editor/render";
import { ToolButton } from "./studio-ui";

interface Props {
  doc: EditDocument;
  asset: EditorState;
  endpoint: string;
  segmentIndex: number;
  select: (index: number) => void;
  onTime: (time: number) => void;
  seekRequest: { time: number; nonce: number };
  update: (change: (doc: EditDocument) => EditDocument, group?: string) => void;
  videoRef: React.RefObject<HTMLVideoElement | null>;
}
export function Preview({
  doc,
  asset,
  endpoint,
  segmentIndex,
  select,
  onTime,
  seekRequest,
  update,
  videoRef,
}: Props) {
  const stageRef = useRef<HTMLDivElement>(null);
  const [previewWidth, setPreviewWidth] = useState(270);
  const canvasRef = useRef<HTMLCanvasElement>(null),
    audioRef = useRef<{ context: AudioContext; gain: GainNode } | null>(null);
  const [playing, setPlaying] = useState(false),
    [loop, setLoop] = useState(true),
    [zone, setZone] = useState<SafeZone>("off"),
    [rate, setRate] = useState(1),
    [mediaError, setMediaError] = useState(false),
    [fontError, setFontError] = useState(false);
  const drag = useRef<{
    x: number;
    y: number;
    startX: number;
    startY: number;
    captionY: number;
    caption: boolean;
    moved: boolean;
  } | null>(null);
  const size = outputSize(doc, asset.width, asset.height);
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const observer = new ResizeObserver(([entry]) =>
      setPreviewWidth(
        Math.min(
          entry.contentRect.width,
          (entry.contentRect.height * size.width) / size.height,
        ),
      ),
    );
    observer.observe(stage);
    return () => observer.disconnect();
  }, [size.width, size.height]);
  const play = useCallback(async () => {
    const video = videoRef.current;
    if (!video) return;
    if (!video.paused) {
      video.pause();
      return;
    }
    if (!audioRef.current && asset.hasAudio) {
      const context = new AudioContext();
      const gain = context.createGain();
      context.createMediaElementSource(video).connect(gain);
      gain.connect(context.destination);
      audioRef.current = { context, gain };
    }
    if (audioRef.current) {
      audioRef.current.gain.gain.value = doc.muted ? 0 : doc.volume;
      await audioRef.current.context.resume();
    }
    const s = doc.segments[segmentIndex];
    if (video.currentTime < s.start || video.currentTime >= s.end - 0.01)
      video.currentTime = s.start;
    await video.play().catch(() => setMediaError(true));
  }, [asset.hasAudio, doc, segmentIndex, videoRef]);
  useEffect(() => {
    void loadEditorFont(doc.captions.font)
      .then(() => setFontError(false))
      .catch(() => setFontError(true));
  }, [doc.captions.font]);
  useEffect(() => {
    const video = videoRef.current;
    if (video) {
      video.muted = doc.muted;
      video.playbackRate = rate;
    }
    if (audioRef.current)
      audioRef.current.gain.gain.value = doc.muted ? 0 : doc.volume;
  }, [doc.volume, doc.muted, rate, videoRef]);
  useEffect(() => {
    const video = videoRef.current;
    if (video) {
      video.currentTime = seekRequest.time;
      onTime(seekRequest.time);
    }
  }, [seekRequest, videoRef, onTime]);
  useEffect(
    () => () => {
      void audioRef.current?.context.close();
    },
    [],
  );
  useEffect(() => {
    let frame: number;
    const draw = () => {
      const canvas = canvasRef.current,
        video = videoRef.current;
      if (canvas && video && video.readyState >= 2) {
        const segment = doc.segments[segmentIndex] ?? doc.segments[0];
        if (!video.paused && video.currentTime >= segment.end - 0.012) {
          const next = segmentIndex + 1;
          if (next < doc.segments.length) {
            video.currentTime = doc.segments[next].start;
            select(next);
          } else if (loop) {
            video.currentTime = doc.segments[0].start;
            select(0);
          } else {
            video.pause();
            video.currentTime = segment.end;
          }
        }
        const at = outputTime(
          doc,
          Math.min(segmentIndex, doc.segments.length - 1),
          video.currentTime,
        );
        // Preview a bleep as silence (the export adds the beep).
        if (audioRef.current)
          audioRef.current.gain.gain.value =
            doc.muted ||
            doc.words.some(
              (w) =>
                w.bleep &&
                video.currentTime >= w.start - 0.05 &&
                video.currentTime < w.end + 0.05,
            )
              ? 0
              : doc.volume;
        const context = canvas.getContext("2d");
        if (context)
          drawEditorFrame(
            context,
            doc,
            video.videoWidth || asset.width,
            video.videoHeight || asset.height,
            at,
            (rect) =>
              context.drawImage(video, rect.x, rect.y, rect.width, rect.height),
          );
      }
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [asset.height, asset.width, doc, loop, segmentIndex, select, videoRef]);
  const step = (direction: number) => {
    const video = videoRef.current;
    if (!video) return;
    video.pause();
    video.currentTime = clamp(
      video.currentTime + direction / asset.fps,
      0,
      asset.duration,
    );
    onTime(video.currentTime);
  };
  const safe = zone !== "off" && doc.framing.aspect === "vertical" && SAFE_ZONES[zone];
  return (
    <section
      aria-label="Video preview"
      className="flex min-h-0 min-w-0 flex-1 flex-col bg-canvas max-lg:h-[70dvh] max-lg:flex-none"
    >
      <div
        ref={stageRef}
        className="relative flex min-h-0 flex-1 items-center justify-center p-4"
      >
        <div
          className="relative max-h-full max-w-full overflow-hidden rounded-lg bg-black shadow-2xl ring-1 ring-white/10"
          style={{
            aspectRatio: `${size.width}/${size.height}`,
            width: `${previewWidth}px`,
          }}
        >
          <video
            ref={videoRef}
            src={`${endpoint}/media/clean.mp4`}
            preload="auto"
            playsInline
            className="hidden"
            onLoadedMetadata={() => {
              if (videoRef.current)
                videoRef.current.currentTime = seekRequest.nonce
                  ? seekRequest.time
                  : doc.segments[0].start;
            }}
            onTimeUpdate={(e) => onTime(e.currentTarget.currentTime)}
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
            onEnded={() => {
              if (loop && videoRef.current) {
                select(0);
                videoRef.current.currentTime = doc.segments[0].start;
                void videoRef.current.play();
              } else setPlaying(false);
            }}
            onError={() => setMediaError(true)}
          />
          <canvas
            ref={canvasRef}
            width={Math.round((size.width / size.height) * 960)}
            height={960}
            aria-label="Edited video preview"
            title="Drag the captions or the video to move them. Click to play or pause."
            className="block h-full w-full cursor-grab touch-none active:cursor-grabbing"
            onPointerDown={(e) => {
              const box = e.currentTarget.getBoundingClientRect();
              drag.current = {
                // Grab the captions near their line; anywhere else moves the video.
                caption:
                  doc.captions.enabled &&
                  Math.abs((e.clientY - box.top) / box.height - doc.captions.y) <
                    0.08,
                moved: false,
                x: e.clientX,
                y: e.clientY,
                startX: doc.framing.x,
                startY: doc.framing.y,
                captionY: doc.captions.y,
              };
              e.currentTarget.setPointerCapture(e.pointerId);
            }}
            onPointerMove={(e) => {
              if (!drag.current) return;
              const box = e.currentTarget.getBoundingClientRect(),
                deltaX = e.clientX - drag.current.x,
                deltaY = e.clientY - drag.current.y;
              if (!drag.current.moved && Math.hypot(deltaX, deltaY) < 4) return;
              drag.current.moved = true;
              if (drag.current.caption) {
                const y = clamp(
                  drag.current.captionY + deltaY / box.height,
                  0.1,
                  0.9,
                );
                update(
                  (d) => ({ ...d, captions: { ...d.captions, y } }),
                  "drag-caption",
                );
              } else {
                // In the stacked layouts the drag moves the gameplay inside its band.
                const stacked =
                    doc.framing.aspect !== "original" &&
                    doc.framing.layout.startsWith("cam_"),
                  paneHeight = box.height * (stacked ? 0.6 : 1);
                const rect = frameRect(
                  stacked ? { ...doc.framing, fit: "cover" } : doc.framing,
                  asset.width,
                  asset.height,
                  box.width,
                  paneHeight,
                );
                const x = clamp(
                    drag.current.startX +
                      (Math.abs(box.width - rect.width) > 1
                        ? deltaX / (box.width - rect.width)
                        : 0),
                    0,
                    1,
                  ),
                  y = clamp(
                    drag.current.startY +
                      (Math.abs(paneHeight - rect.height) > 1
                        ? deltaY / (paneHeight - rect.height)
                        : 0),
                    0,
                    1,
                  );
                update(
                  (d) => ({ ...d, framing: { ...d.framing, x, y } }),
                  "drag-frame",
                );
              }
            }}
            onPointerUp={() => {
              if (drag.current && !drag.current.moved) void play();
              drag.current = null;
            }}
            onPointerCancel={() => {
              drag.current = null;
            }}
          />
          {safe && (
            <div
              aria-label={`${safe.label} safe zone`}
              className="pointer-events-none absolute inset-0 text-[10px] font-medium text-white/90 [&>div]:absolute [&>div]:bg-red-500/30 [&>div]:outline [&>div]:outline-dashed [&>div]:outline-1 [&>div]:outline-red-300/70"
            >
              <div
                className="inset-x-0 top-0 flex items-center justify-center"
                style={{ height: `${safe.top}%` }}
              >
                {safe.label} header
              </div>
              <div
                className="inset-x-0 bottom-0 flex items-center justify-center"
                style={{ height: `${safe.bottom}%` }}
              >
                Caption, sound and nav
              </div>
              <div
                className="right-0 top-[45%]"
                style={{ width: `${safe.right}%`, bottom: `${safe.bottom}%` }}
              />
            </div>
          )}
          {mediaError && (
            <div className="absolute inset-0 flex flex-col justify-center gap-3 bg-stone-950/90 p-5 text-center text-sm text-white">
              <p>Preview could not load.</p>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  setMediaError(false);
                  videoRef.current?.load();
                }}
              >
                Retry preview
              </Button>
            </div>
          )}
        </div>
        {fontError && (
          <p className="absolute inset-x-0 bottom-1 px-4 text-center text-[11px] text-amber-300">
            Caption font could not load. Check your connection before exporting.
          </p>
        )}
      </div>
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 border-t bg-card px-3 py-1.5">
        <div className="flex items-center gap-1">
          <Tooltip>
            <TooltipTrigger asChild>
              <Toggle
                size="sm"
                aria-label="Loop selected edit"
                pressed={loop}
                onPressedChange={setLoop}
              >
                <Repeat />
              </Toggle>
            </TooltipTrigger>
            <TooltipContent>Loop playback</TooltipContent>
          </Tooltip>
          <Select
            value={String(rate)}
            onValueChange={(value) => setRate(Number(value))}
          >
            <SelectTrigger
              size="sm"
              aria-label="Preview playback speed"
              className="h-8 w-[4.5rem] border-transparent shadow-none hover:bg-accent tabular-nums"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {[0.5, 0.75, 1, 1.25, 1.5, 2].map((n) => (
                <SelectItem key={n} value={String(n)}>
                  {n}×
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-center gap-1">
          <ToolButton
            label="Previous frame"
            shortcut="←"
            onClick={() => step(-1)}
          >
            <SkipBack />
          </ToolButton>
          <Button
            size="icon"
            className="rounded-full"
            aria-label={playing ? "Pause" : "Play"}
            onClick={() => void play()}
          >
            {playing ? (
              <Pause className="fill-current" />
            ) : (
              <Play className="ml-0.5 fill-current" />
            )}
          </Button>
          <ToolButton label="Next frame" shortcut="→" onClick={() => step(1)}>
            <SkipForward />
          </ToolButton>
        </div>
        <div className="flex items-center justify-end gap-2">
          {doc.muted && (
            <VolumeX
              aria-label="Muted"
              className="size-3.5 text-muted-foreground"
            />
          )}
          <span className="text-[11px] tabular-nums text-muted-foreground max-md:hidden">
            {size.width} × {size.height} · {Math.round(asset.fps)} fps
          </span>
          <Select value={zone} onValueChange={(v) => setZone(v as SafeZone)}>
            <SelectTrigger
              size="sm"
              aria-label="Safe zones"
              className="h-8 border-transparent text-xs shadow-none hover:bg-accent"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="end">
              <SelectItem value="off">Safe zones off</SelectItem>
              {Object.entries(SAFE_ZONES).map(([id, z]) => (
                <SelectItem key={id} value={id}>
                  {z.label} safe zone
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
    </section>
  );
}
