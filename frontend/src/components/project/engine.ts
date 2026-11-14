import { drawWords, loadEditorFont } from "@/lib/editor/render";
import {
  clipEnd,
  clipValues,
  docDuration,
  fadeAt,
  type Assets,
  type Clip,
  type ProjectDocument,
  type TimedWord,
} from "@/lib/project/document";

interface Deck {
  el: HTMLVideoElement | HTMLAudioElement;
  clip: string | null;
  asset: string | null;
}
const clamp01 = (value: number) => Math.min(1, Math.max(0, value));

/**
 * Plays the timeline in the browser: the preview copies of the clips under the playhead are
 * drawn on a canvas in layer order, with text and captions on top.
 *
 * Each track owns two players. One plays the current clip while the other is already parked on
 * the start of the next one, so playback crosses a cut without waiting for a seek.
 * The export (backend/src/project_document.py) draws the same picture with ffmpeg.
 */
export class Engine {
  time = 0;
  playing = false;
  doc: ProjectDocument | null = null;
  private assets: Assets = {};
  private lines: TimedWord[][] = [];
  private byTrack = new Map<string, Clip[]>();
  private decks = new Map<string, Deck[]>();
  private images = new Map<string, HTMLImageElement>();
  private listeners = new Set<() => void>();
  private raf = 0;
  private last = 0;
  private waiting = false;
  private ctx: CanvasRenderingContext2D;

  constructor(
    private canvas: HTMLCanvasElement,
    private endpoint: string,
  ) {
    this.ctx = canvas.getContext("2d")!;
    this.raf = requestAnimationFrame(this.frame);
  }

  /** Called on every time or play-state change; returns the unsubscribe. */
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  private emit() {
    this.listeners.forEach((listener) => listener());
  }

  set(doc: ProjectDocument, assets: Assets, lines: TimedWord[][]) {
    this.doc = doc;
    this.assets = assets;
    this.lines = lines;
    this.byTrack.clear();
    for (const clip of doc.clips) {
      const list = this.byTrack.get(clip.track);
      if (list) list.push(clip);
      else this.byTrack.set(clip.track, [clip]);
    }
    this.byTrack.forEach((list) => list.sort((a, b) => a.start - b.start));
    // Preview at up to 1280 wide: sharp enough to edit by, light enough to stay smooth.
    const width = Math.min(1280, doc.width),
      height = Math.round((width * doc.height) / doc.width);
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
    }
    for (const font of new Set([doc.captions.font, ...doc.clips.flatMap((c) => (c.text ? [c.text.font] : []))]))
      void loadEditorFont(font).catch(() => {});
    if (this.time > docDuration(doc)) this.seek(docDuration(doc));
  }

  seek(time: number) {
    this.time = Math.max(0, Math.min(time, this.doc ? docDuration(this.doc) : 0));
    this.emit();
  }
  play() {
    if (!this.doc || this.playing) return;
    if (this.time >= docDuration(this.doc) - 0.05) this.time = 0;
    this.playing = true;
    this.last = performance.now();
    this.emit();
  }
  pause() {
    if (!this.playing) return;
    this.playing = false;
    this.emit();
  }
  toggle() {
    if (this.playing) this.pause();
    else this.play();
  }
  destroy() {
    cancelAnimationFrame(this.raf);
    this.decks.forEach((pair) =>
      pair.forEach((deck) => {
        deck.el.pause();
        deck.el.removeAttribute("src");
        deck.el.load();
      }),
    );
    this.listeners.clear();
  }

  /** The clip playing at `time` on a track and the one after it. */
  private around(track: string, time: number) {
    const list = this.byTrack.get(track) ?? [];
    let lo = 0,
      hi = list.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (list[mid].start <= time) lo = mid + 1;
      else hi = mid;
    }
    const before = list[lo - 1];
    return {
      active: before && time < clipEnd(before) ? before : null,
      next: list[lo] as Clip | undefined,
    };
  }
  private playable(clip: Clip | null | undefined) {
    const asset = clip?.asset ? this.assets[clip.asset] : undefined;
    return asset?.status === "ready" && asset.kind !== "image" ? asset : undefined;
  }
  private decksFor(track: string, kind: "video" | "audio") {
    let pair = this.decks.get(track);
    if (!pair) {
      pair = [0, 1].map(() => {
        const el = document.createElement(kind);
        el.preload = "auto";
        if (el instanceof HTMLVideoElement) el.playsInline = true;
        return { el, clip: null, asset: null };
      });
      this.decks.set(track, pair);
    }
    return pair;
  }
  private load(deck: Deck, clip: Clip, time: number) {
    const asset = this.assets[clip.asset!];
    if (deck.asset !== asset.id) {
      deck.el.src = `${this.endpoint}/assets/${asset.id}/${asset.kind === "audio" ? "audio.m4a" : "proxy.mp4"}`;
      deck.asset = asset.id;
    }
    deck.el.currentTime = time;
    deck.clip = clip.id;
  }

  /** Lines the track's players up with the timeline and returns the one showing now. */
  private sync(track: ProjectDocument["tracks"][number], time: number) {
    const { active, next } = this.around(track.id, time);
    const pair = this.decksFor(track.id, track.kind === "audio" ? "audio" : "video");
    let current: Deck | null = null;
    if (active && this.playable(active)) {
      current =
        pair.find((d) => d.clip === active.id) ?? null;
      const expected = active.offset + (time - active.start) * active.speed;
      if (!current) {
        current = pair.find((d) => d.clip !== next?.id) ?? pair[0];
        this.load(current, active, expected);
      }
      const el = current.el,
        drift = Math.abs(el.currentTime - expected);
      if (el.playbackRate !== active.speed) el.playbackRate = active.speed;
      if (this.playing) {
        if (drift > 0.3 && !el.seeking) el.currentTime = expected;
        if (el.paused && el.readyState >= 2) void el.play().catch(() => {});
        if (el.readyState < 3 && !el.error) this.waiting = true;
      } else {
        if (!el.paused) el.pause();
        if (drift > 0.02 && !el.seeking) el.currentTime = expected;
      }
      const silent = track.muted || active.muted;
      // ponytail: the preview tops out at normal volume; boosts above 100% are heard in the export.
      el.volume = silent ? 0 : clamp01(active.volume * fadeAt(active, time - active.start));
      el.muted = silent;
    }
    for (const deck of pair) {
      if (deck === current) continue;
      if (!deck.el.paused) deck.el.pause();
      // Park the spare player on the next clip a few seconds ahead of the cut.
      if (next && this.playable(next) && next.start - time < 4) {
        if (deck.clip !== next.id || Math.abs(deck.el.currentTime - next.offset) > 0.05)
          if (!deck.el.seeking) this.load(deck, next, next.offset);
      }
    }
    return { active, deck: current };
  }

  private image(asset: string) {
    let image = this.images.get(asset);
    if (!image) {
      image = new Image();
      image.src = `${this.endpoint}/assets/${asset}/image`;
      this.images.set(asset, image);
    }
    return image.complete && image.naturalWidth ? image : null;
  }

  private frame = (now: number) => {
    this.raf = requestAnimationFrame(this.frame);
    const doc = this.doc;
    if (!doc) return;
    if (this.playing) {
      // Hold the clock while a player is still loading, so sound and picture stay together.
      if (!this.waiting) this.time += Math.min(0.1, (now - this.last) / 1000);
      this.last = now;
      if (this.time >= docDuration(doc)) {
        this.time = docDuration(doc);
        this.playing = false;
      }
      this.emit();
    }
    this.waiting = false;
    const { ctx } = this,
      { width, height } = this.canvas,
      time = this.time;
    ctx.globalAlpha = 1;
    ctx.fillStyle = "black";
    ctx.fillRect(0, 0, width, height);
    for (const track of doc.tracks) {
      if (track.kind === "text") continue;
      const { active, deck } = this.sync(track, time);
      if (!active || track.kind !== "video" || track.hidden) continue;
      const asset = this.assets[active.asset ?? ""];
      if (!asset || asset.status !== "ready") continue;
      const source =
        asset.kind === "image"
          ? this.image(asset.id)
          : deck && (deck.el as HTMLVideoElement).readyState >= 2
            ? (deck.el as HTMLVideoElement)
            : null;
      if (!source) continue;
      const local = time - active.start,
        v = clipValues(active, local),
        fit = Math.min(width / asset.width, height / asset.height),
        w = asset.width * fit * v.scale,
        h = asset.height * fit * v.scale;
      ctx.globalAlpha = clamp01(v.opacity * fadeAt(active, local));
      ctx.drawImage(source, v.x * width - w / 2, v.y * height - h / 2, w, h);
    }
    for (const track of doc.tracks) {
      if (track.kind !== "text" || track.hidden) continue;
      const { active } = this.around(track.id, time);
      if (!active?.text?.content.trim()) continue;
      const local = time - active.start,
        v = clipValues(active, local),
        style = { ...active.text, size: active.text.size * v.scale, accent: active.text.color },
        rows = active.text.content.split("\n");
      ctx.globalAlpha = clamp01(v.opacity * fadeAt(active, local));
      rows.forEach((row, index) =>
        drawWords(
          ctx,
          style as Parameters<typeof drawWords>[1],
          row.split(/\s+/).filter(Boolean).map((text) => ({ text })),
          v.y + ((index - (rows.length - 1) / 2) * style.size * 1.2 * (width / 1080)) / height,
          () => false,
          v.x,
        ),
      );
    }
    ctx.globalAlpha = 1;
    if (!doc.captions.enabled) return;
    const line = this.lineAt(time);
    if (!line) return;
    const spoken = doc.captions.active ? line.findLastIndex((w) => w.start <= time) : -1;
    drawWords(ctx, doc.captions, line, doc.captions.y, (i) => i === spoken);
  };

  private lineAt(time: number) {
    const lines = this.lines;
    let lo = 0,
      hi = lines.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (lines[mid][0].start <= time) lo = mid + 1;
      else hi = mid;
    }
    const line = lines[lo - 1];
    return line && time < Math.max(...line.map((w) => w.end)) ? line : null;
  }
}
