/**
 * The long-form project document and every edit that can be made to it.
 *
 * Edits are pure functions (document in, document out) so the timeline, the transcript panel
 * and the AI assistant all change a project the same way and every change can be undone.
 * The server validates and renders the same shape: backend/src/project_document.py.
 */
import { captionGroups, uid, type CaptionStyle } from "@/lib/editor/document";

export interface Track {
  id: string;
  kind: "video" | "audio" | "text";
  name: string;
  muted: boolean;
  hidden: boolean;
  locked: boolean;
}
export interface TextStyle {
  content: string;
  font: string;
  size: number;
  color: string;
  background: boolean;
  outline: number;
  uppercase: boolean;
}
/** The animated properties `t` seconds into a clip; values run in straight lines between keys. */
export interface Keyframe {
  t: number;
  x: number;
  y: number;
  scale: number;
  opacity: number;
}
export interface Clip {
  id: string;
  track: string;
  /** Position and length on the timeline, in seconds. */
  start: number;
  duration: number;
  /** null for text clips. */
  asset: string | null;
  /** Where in the source the clip begins. */
  offset: number;
  speed: number;
  /** Centre of the picture as a share of the frame; scale 1 fits it inside the frame. */
  x: number;
  y: number;
  scale: number;
  opacity: number;
  volume: number;
  muted: boolean;
  fadeIn: number;
  fadeOut: number;
  text: TextStyle | null;
  keys: Keyframe[];
  link: string | null;
}
/** A removed stretch of a source, kept so the transcript can show it struck through and restore it. */
export interface Cut {
  asset: string;
  start: number;
  end: number;
  reason: "manual" | "silence" | "filler" | "ai";
}
export interface Chapter {
  time: number;
  title: string;
}
export interface ProjectDocument {
  version: 1;
  width: number;
  height: number;
  fps: number;
  /** Video tracks are listed bottom layer first. */
  tracks: Track[];
  clips: Clip[];
  captions: CaptionStyle;
  /** Corrected caption text per asset and word index; "" hides the word. */
  wordEdits: Record<string, Record<string, string>>;
  cuts: Cut[];
  chapters: Chapter[];
  title: string;
  description: string;
  /** Export only: less rumble and hiss, steadier voice level, on the clips of the video tracks. */
  cleanVoice?: boolean;
}
export interface Asset {
  id: string;
  name: string;
  kind: "video" | "audio" | "image";
  status: "preparing" | "ready" | "failed";
  progress: number;
  error?: string;
  duration: number;
  width: number;
  height: number;
  fps: number;
  hasAudio: boolean;
  transcript?: "none" | "pending" | "ready" | "failed";
  waveRate?: number;
  thumbs?: {
    step: number;
    columns: number;
    width: number;
    height: number;
    count: number;
  };
}
/** A spoken word in source seconds. */
export interface Word {
  s: number;
  e: number;
  t: string;
}
export type Assets = Record<string, Asset>;

const MIN = 0.04;
const EPS = 0.002;
const round = (value: number) => Math.round(value * 1000) / 1000;
export const clipEnd = (clip: Clip) => clip.start + clip.duration;
export const sourceEnd = (clip: Clip) =>
  clip.offset + clip.duration * clip.speed;
export const docDuration = (doc: ProjectDocument) =>
  doc.clips.reduce((end, c) => Math.max(end, clipEnd(c)), 0);
export const trackOf = (doc: ProjectDocument, clip: Clip) =>
  doc.tracks.find((t) => t.id === clip.track)!;
/** The first video track: cuts made in the transcript close up, like a film strip. */
export const mainTrack = (doc: ProjectDocument) =>
  doc.tracks.find((t) => t.kind === "video")!;

export function newClip(values: Partial<Clip> & Pick<Clip, "track">): Clip {
  return {
    id: uid().replace(/-/g, "").slice(0, 12),
    start: 0,
    duration: 5,
    asset: null,
    offset: 0,
    speed: 1,
    x: 0.5,
    y: 0.5,
    scale: 1,
    opacity: 1,
    volume: 1,
    muted: false,
    fadeIn: 0,
    fadeOut: 0,
    text: null,
    keys: [],
    link: null,
    ...values,
  };
}

/** (x, y, scale, opacity) `t` seconds into the clip. Mirrors clip_values in project_document.py. */
export function clipValues(clip: Clip, t: number) {
  const { x, y, scale, opacity } = clip;
  if (!clip.keys.length) return { x, y, scale, opacity };
  const keys = [...clip.keys].sort((a, b) => a.t - b.t);
  if (t <= keys[0].t) return keys[0];
  for (let i = 1; i < keys.length; i++) {
    const a = keys[i - 1],
      b = keys[i];
    if (t <= b.t) {
      const f = b.t > a.t ? (t - a.t) / (b.t - a.t) : 1;
      const mix = (p: number, q: number) => p + (q - p) * f;
      return {
        x: mix(a.x, b.x),
        y: mix(a.y, b.y),
        scale: mix(a.scale, b.scale),
        opacity: mix(a.opacity, b.opacity),
      };
    }
  }
  return keys[keys.length - 1];
}
/** 0..1 brightness of a clip from its fade in and out, `t` seconds in. */
export const fadeAt = (clip: Clip, t: number) =>
  Math.max(
    0,
    Math.min(
      1,
      clip.fadeIn ? t / clip.fadeIn : 1,
      clip.fadeOut ? (clip.duration - t) / clip.fadeOut : 1,
    ),
  );

// ------------------------------------------------------------------ placing clips

/** The first start at or after `start` where a clip of `duration` fits on the track. */
export function freeStart(
  doc: ProjectDocument,
  track: string,
  start: number,
  duration: number,
  ignore: ReadonlySet<string> = new Set(),
) {
  const others = doc.clips
    .filter((c) => c.track === track && !ignore.has(c.id))
    .sort((a, b) => a.start - b.start);
  let at = Math.max(0, start);
  for (const other of others)
    if (other.start < at + duration - EPS && clipEnd(other) > at + EPS)
      at = clipEnd(other);
  return round(at);
}
const trackEnd = (doc: ProjectDocument, track: string) =>
  doc.clips
    .filter((c) => c.track === track)
    .reduce((end, c) => Math.max(end, clipEnd(c)), 0);

/** Puts a file on the timeline: on `track` at `at` when given, otherwise at the end of the first track of its kind. */
export function addAssetClip(
  doc: ProjectDocument,
  asset: Asset,
  track?: string,
  at?: number,
): ProjectDocument {
  const kind = asset.kind === "audio" ? "audio" : "video";
  const videoTracks = doc.tracks.filter((t) => t.kind === "video");
  const target =
    doc.tracks.find((t) => t.id === track && t.kind === kind) ??
    // Pictures go over the video, not into the main track, unless nothing else is there.
    (asset.kind === "image" && doc.clips.length ? videoTracks[1] : undefined) ??
    doc.tracks.find((t) => t.kind === kind);
  if (!target) return doc;
  const duration = asset.kind === "image" ? 5 : asset.duration;
  if (duration < MIN) return doc;
  const first = !doc.clips.some((c) => c.asset);
  const clip = newClip({
    track: target.id,
    asset: asset.id,
    duration: round(duration),
    // A small picture (a logo, an emote) keeps its own size instead of filling the frame.
    scale:
      asset.kind === "image" && asset.width && target.id !== videoTracks[0]?.id
        ? Math.min(1, Math.max(0.05, round(Math.max(asset.width / doc.width, asset.height / doc.height))))
        : 1,
    start: freeStart(
      doc,
      target.id,
      at ?? trackEnd(doc, target.id),
      duration,
    ),
  });
  return {
    ...doc,
    // The first video decides the shape and frame rate of the project.
    ...(first && asset.kind === "video" && asset.width && asset.height
      ? {
          width: Math.min(3840, Math.round(asset.width / 2) * 2),
          height: Math.min(3840, Math.round(asset.height / 2) * 2),
          fps: Math.min(60, Math.max(1, Math.round(asset.fps * 1000) / 1000)),
        }
      : {}),
    clips: [...doc.clips, clip],
  };
}

export function addTextClip(doc: ProjectDocument, at: number): ProjectDocument {
  const track = doc.tracks.find((t) => t.kind === "text");
  if (!track) return doc;
  const clip = newClip({
    track: track.id,
    duration: 4,
    start: freeStart(doc, track.id, at, 4),
    text: {
      content: "Your text",
      font: "Poppins-ExtraBold",
      size: 70,
      color: "#FFFFFF",
      background: false,
      outline: 4,
      uppercase: false,
    },
  });
  return { ...doc, clips: [...doc.clips, clip] };
}

export function patchClips(
  doc: ProjectDocument,
  ids: ReadonlySet<string>,
  patch: Partial<Clip> | ((clip: Clip) => Partial<Clip>),
): ProjectDocument {
  return {
    ...doc,
    clips: doc.clips.map((c) =>
      ids.has(c.id)
        ? { ...c, ...(typeof patch === "function" ? patch(c) : patch) }
        : c,
    ),
  };
}

/** Moves the selected clips by `delta` seconds; `track` moves the grabbed clip to another track of its kind. */
export function moveClips(
  doc: ProjectDocument,
  ids: ReadonlySet<string>,
  delta: number,
  grabbed?: string,
  track?: string,
): ProjectDocument {
  const moving = doc.clips.filter((c) => ids.has(c.id));
  if (!moving.length) return doc;
  delta = Math.max(delta, -Math.min(...moving.map((c) => c.start)));
  let next = doc;
  // Left-most first when moving left (and the reverse), so moved clips do not block each other.
  for (const clip of [...moving].sort((a, b) =>
    delta < 0 ? a.start - b.start : b.start - a.start,
  )) {
    const target =
      clip.id === grabbed &&
      track &&
      doc.tracks.find((t) => t.id === track)?.kind === trackOf(doc, clip).kind
        ? track
        : clip.track;
    const start = freeStart(
      next,
      target,
      clip.start + delta,
      clip.duration,
      target === clip.track ? ids : new Set([clip.id]),
    );
    next = patchClips(next, new Set([clip.id]), { start, track: target });
  }
  return next;
}

/** Drags one edge of a clip to `time`, within its source and its neighbours. */
export function trimClip(
  doc: ProjectDocument,
  id: string,
  edge: "start" | "end",
  time: number,
  assets: Assets,
): ProjectDocument {
  const clip = doc.clips.find((c) => c.id === id);
  if (!clip) return doc;
  const asset = clip.asset ? assets[clip.asset] : undefined;
  const fixed = !asset || asset.kind === "image"; // text and pictures have no source length
  const others = doc.clips.filter((c) => c.track === clip.track && c.id !== id);
  if (edge === "start") {
    const floor = Math.max(
      0,
      ...others.filter((c) => clipEnd(c) <= clip.start + EPS).map(clipEnd),
      fixed ? 0 : clip.start - clip.offset / clip.speed,
    );
    const start = round(
      Math.min(Math.max(time, floor), clipEnd(clip) - MIN),
    );
    const moved = start - clip.start;
    return patchClips(doc, new Set([id]), {
      start,
      duration: round(clip.duration - moved),
      offset: fixed ? 0 : round(Math.max(0, clip.offset + moved * clip.speed)),
      keys: clip.keys.map((k) => ({ ...k, t: Math.max(0, k.t - moved) })),
    });
  }
  const ceiling = Math.min(
    ...others.filter((c) => c.start >= clipEnd(clip) - EPS).map((c) => c.start),
    fixed
      ? Infinity
      : clip.start + (asset!.duration - clip.offset) / clip.speed,
  );
  const end = Math.max(Math.min(time, ceiling), clip.start + MIN);
  return patchClips(doc, new Set([id]), {
    duration: round(end - clip.start),
  });
}

/** Cuts a clip in two at a timeline time. */
export function splitClip(
  doc: ProjectDocument,
  id: string,
  time: number,
): ProjectDocument {
  const clip = doc.clips.find((c) => c.id === id);
  if (!clip || time - clip.start < MIN || clipEnd(clip) - time < MIN)
    return doc;
  const head = round(time - clip.start);
  const left: Clip = {
    ...clip,
    duration: head,
    fadeOut: 0,
    keys: clip.keys.filter((k) => k.t <= head),
  };
  const right: Clip = {
    ...clip,
    id: newClip({ track: clip.track }).id,
    start: round(time),
    duration: round(clip.duration - head),
    offset: clip.text ? 0 : round(clip.offset + head * clip.speed),
    fadeIn: 0,
    keys: clip.keys
      .filter((k) => k.t > head)
      .map((k) => ({ ...k, t: k.t - head })),
  };
  return {
    ...doc,
    clips: doc.clips.flatMap((c) => (c.id === id ? [left, right] : [c])),
  };
}

/** Splits the selected clips under `time`, or every unlocked clip there when nothing is selected. */
export function splitAt(
  doc: ProjectDocument,
  time: number,
  selected: ReadonlySet<string>,
): ProjectDocument {
  const under = doc.clips.filter(
    (c) =>
      c.start < time - EPS &&
      clipEnd(c) > time + EPS &&
      !trackOf(doc, c).locked &&
      (!selected.size || selected.has(c.id)),
  );
  return under.reduce((next, clip) => splitClip(next, clip.id, time), doc);
}

/** Closes the timeline over [from, to): every later clip on an unlocked track moves left. */
function closeGap(
  doc: ProjectDocument,
  from: number,
  to: number,
): ProjectDocument {
  const locked = new Set(doc.tracks.filter((t) => t.locked).map((t) => t.id));
  return {
    ...doc,
    clips: doc.clips.map((c) =>
      c.start >= to - EPS && !locked.has(c.track)
        ? { ...c, start: round(Math.max(0, c.start - (to - from))) }
        : c,
    ),
    chapters: doc.chapters
      .filter((c) => c.time < from || c.time >= to)
      .map((c) =>
        c.time >= to ? { ...c, time: round(c.time - (to - from)) } : c,
      ),
  };
}
/** Opens `length` seconds of room at `at`, the reverse of closeGap. */
function openGap(
  doc: ProjectDocument,
  at: number,
  length: number,
  except: ReadonlySet<string>,
): ProjectDocument {
  const locked = new Set(doc.tracks.filter((t) => t.locked).map((t) => t.id));
  return {
    ...doc,
    clips: doc.clips.map((c) =>
      c.start >= at - EPS && !locked.has(c.track) && !except.has(c.id)
        ? { ...c, start: round(c.start + length) }
        : c,
    ),
    chapters: doc.chapters.map((c) =>
      c.time >= at ? { ...c, time: round(c.time + length) } : c,
    ),
  };
}

/** Deletes clips. With `ripple`, the space each one leaves is closed up. */
export function deleteClips(
  doc: ProjectDocument,
  ids: ReadonlySet<string>,
  ripple: boolean,
): ProjectDocument {
  const gone = doc.clips
    .filter((c) => ids.has(c.id))
    .sort((a, b) => b.start - a.start);
  let next = { ...doc, clips: doc.clips.filter((c) => !ids.has(c.id)) };
  if (ripple)
    for (const clip of gone) {
      // Only close space that is now empty on that track.
      const busy = next.clips.some(
        (c) =>
          c.track === clip.track &&
          c.start < clipEnd(clip) - EPS &&
          clipEnd(c) > clip.start + EPS,
      );
      if (!busy) next = closeGap(next, clip.start, clipEnd(clip));
    }
  return next;
}

// ------------------------------------------------------------------ cutting by source time (transcript edits)

/** Removes [start, end) of a source from every clip that shows it, closes the gaps and records the cut. */
export function cutSource(
  doc: ProjectDocument,
  asset: string,
  start: number,
  end: number,
  reason: Cut["reason"] = "manual",
): ProjectDocument {
  if (end - start < 0.01) return doc;
  let next = doc,
    changed = false;
  const hit = doc.clips
    .filter(
      (c) =>
        c.asset === asset &&
        !trackOf(doc, c).locked &&
        c.offset < end - EPS &&
        sourceEnd(c) > start + EPS,
    )
    .sort((a, b) => b.start - a.start);
  for (const clip of hit) {
    const from = Math.max(clip.start, clip.start + (start - clip.offset) / clip.speed),
      to = Math.min(clipEnd(clip), clip.start + (end - clip.offset) / clip.speed);
    const keepHead = from - clip.start >= MIN,
      keepTail = clipEnd(clip) - to >= MIN;
    // A sliver shorter than a frame goes with the cut.
    const a = keepHead ? from : clip.start,
      b = keepTail ? to : clipEnd(clip);
    let clips = next.clips;
    if (keepHead && keepTail) {
      const tail = newClip({ track: clip.track }).id;
      clips = clips.flatMap((c) =>
        c.id === clip.id
          ? [
              {
                ...c,
                duration: round(a - c.start),
                fadeOut: 0,
                keys: c.keys.filter((k) => k.t <= a - c.start),
              },
              {
                ...c,
                id: tail,
                start: round(b),
                duration: round(clipEnd(c) - b),
                offset: round(c.offset + (b - c.start) * c.speed),
                fadeIn: 0,
                keys: c.keys
                  .filter((k) => k.t >= b - c.start)
                  .map((k) => ({ ...k, t: k.t - (b - c.start) })),
              },
            ]
          : [c],
      );
    } else if (keepHead)
      clips = clips.map((c) =>
        c.id === clip.id ? { ...c, duration: round(a - c.start), fadeOut: 0 } : c,
      );
    else if (keepTail)
      clips = clips.map((c) =>
        c.id === clip.id
          ? {
              ...c,
              start: round(b),
              duration: round(clipEnd(c) - b),
              offset: round(c.offset + (b - c.start) * c.speed),
              fadeIn: 0,
            }
          : c,
      );
    else clips = clips.filter((c) => c.id !== clip.id);
    next = closeGap({ ...next, clips }, a, b);
    changed = true;
  }
  if (!changed) return doc;
  return {
    ...next,
    // A wider cut swallows the records of the cuts inside it.
    cuts: [
      ...next.cuts.filter(
        (c) => c.asset !== asset || c.start < start - EPS || c.end > end + EPS,
      ),
      { asset, start: round(start), end: round(end), reason },
    ],
  };
}

/** Applies many cuts to one source in a single edit. */
export function cutRanges(
  doc: ProjectDocument,
  asset: string,
  ranges: [number, number][],
  reason: Cut["reason"],
): ProjectDocument {
  // Last first, so earlier clips have not moved when their turn comes.
  return [...ranges]
    .sort((a, b) => b[0] - a[0])
    .reduce((next, [s, e]) => cutSource(next, asset, s, e, reason), doc);
}

/** Puts a recorded cut back, widening the clips either side of it. */
export function restoreCut(doc: ProjectDocument, cut: Cut): ProjectDocument {
  const cuts = doc.cuts.filter((c) => c !== cut);
  const near = (a: number, b: number) => Math.abs(a - b) < 0.02;
  const left = doc.clips.find(
    (c) => c.asset === cut.asset && near(sourceEnd(c), cut.start),
  );
  const right = doc.clips.find(
    (c) =>
      c.asset === cut.asset &&
      near(c.offset, cut.end) &&
      (!left || (c.track === left.track && near(c.start, clipEnd(left)))),
  );
  const length = (cut.end - cut.start) / ((left ?? right)?.speed ?? 1);
  if (left && right) {
    const opened = openGap(doc, right.start, length, new Set());
    return {
      ...opened,
      cuts,
      clips: opened.clips
        .filter((c) => c.id !== right.id)
        .map((c) =>
          c.id === left.id
            ? {
                ...c,
                duration: round(c.duration + length + right.duration),
                fadeOut: right.fadeOut,
              }
            : c,
        ),
    };
  }
  if (left) {
    const opened = openGap(doc, clipEnd(left), length, new Set());
    return {
      ...opened,
      cuts,
      clips: opened.clips.map((c) =>
        c.id === left.id ? { ...c, duration: round(c.duration + length) } : c,
      ),
    };
  }
  if (right) {
    const opened = openGap(doc, right.start, length, new Set([right.id]));
    return {
      ...opened,
      cuts,
      clips: opened.clips.map((c) =>
        c.id === right.id
          ? {
              ...c,
              offset: round(cut.start),
              duration: round(c.duration + length),
            }
          : c,
      ),
    };
  }
  // Neither side is on the timeline any more: put the stretch back as its own clip.
  const track = mainTrack(doc);
  const before = doc.clips
    .filter((c) => c.asset === cut.asset && c.track === track.id && c.offset < cut.start)
    .sort((a, b) => b.offset - a.offset)[0];
  const at = before ? clipEnd(before) : 0;
  const opened = openGap(doc, at, cut.end - cut.start, new Set());
  return {
    ...opened,
    cuts,
    clips: [
      ...opened.clips,
      newClip({
        track: track.id,
        asset: cut.asset,
        start: round(at),
        offset: cut.start,
        duration: round(cut.end - cut.start),
      }),
    ],
  };
}

export function restoreCuts(
  doc: ProjectDocument,
  match: (cut: Cut) => boolean,
): ProjectDocument {
  return [...doc.cuts]
    .filter(match)
    .sort((a, b) => b.start - a.start)
    .reduce(
      (next, cut) =>
        restoreCut(
          next,
          next.cuts.find(
            (c) => c.asset === cut.asset && c.start === cut.start && c.end === cut.end,
          )!,
        ),
      doc,
    );
}

// ------------------------------------------------------------------ transcript

/** Which stretches of a source are on the timeline, merged and in source order. */
export function keptRanges(doc: ProjectDocument, asset: string) {
  const ranges = doc.clips
    .filter((c) => c.asset === asset)
    .map((c) => [c.offset, sourceEnd(c)] as [number, number])
    .sort((a, b) => a[0] - b[0]);
  const merged: [number, number][] = [];
  for (const range of ranges) {
    const last = merged[merged.length - 1];
    if (last && range[0] <= last[1] + EPS) last[1] = Math.max(last[1], range[1]);
    else merged.push([...range]);
  }
  return merged;
}
/** For each word, whether it is still on the timeline. */
export function keptWords(words: Word[], ranges: [number, number][]) {
  const kept = new Uint8Array(words.length);
  let r = 0;
  words.forEach((word, i) => {
    while (r < ranges.length && ranges[r][1] <= word.s + EPS) r++;
    kept[i] = r < ranges.length && ranges[r][0] <= word.s + EPS ? 1 : 0;
  });
  return kept;
}
/** Where a source moment plays on the timeline, or null when it has been cut. */
export function timelineTime(doc: ProjectDocument, asset: string, time: number) {
  const clip = doc.clips.find(
    (c) => c.asset === asset && c.offset <= time + EPS && sourceEnd(c) > time + EPS,
  );
  return clip ? clip.start + (time - clip.offset) / clip.speed : null;
}

/** The source range that removes words[first..last] cleanly, taking half of the pause either side. */
export function wordRange(
  words: Word[],
  first: number,
  last: number,
): [number, number] {
  const before = words[first - 1]?.e ?? 0,
    after = words[last + 1]?.s ?? words[last].e + 0.2;
  // Up to 0.15 s of the pause either side goes with the words, never more than half of it.
  const pad = (gap: number) => Math.min(0.15, Math.max(0, gap / 2));
  return [
    words[first].s - pad(words[first].s - before),
    words[last].e + pad(after - words[last].e),
  ];
}

export interface SilenceOptions {
  /** Pauses at least this long are removed. */
  minPause: number;
  /** Breathing room left either side of the speech. */
  padding: number;
  /** Keep pauses where the audio stays loud (gameplay with nobody talking). */
  keepLoud: boolean;
}
/** Pauses between spoken words, as source ranges to cut. */
export function findSilences(
  words: Word[],
  duration: number,
  options: SilenceOptions,
  wave?: Uint8Array,
  waveRate = 20,
): [number, number][] {
  const level = (from: number, to: number) => {
    if (!wave) return 0;
    const a = Math.floor(from * waveRate),
      b = Math.max(a + 1, Math.ceil(to * waveRate));
    let sum = 0;
    for (let i = a; i < b && i < wave.length; i++) sum += wave[i];
    return sum / (b - a);
  };
  // "Loud" is judged against how loud this recording is while someone is talking.
  let speech = 0;
  if (wave && options.keepLoud && words.length) {
    const sample = words.filter((_, i) => i % Math.ceil(words.length / 400) === 0);
    speech = sample.reduce((sum, w) => sum + level(w.s, w.e), 0) / sample.length;
  }
  const ranges: [number, number][] = [];
  const consider = (from: number, to: number) => {
    if (to - from < options.minPause) return;
    const a = from + options.padding,
      b = to - options.padding;
    if (b - a < 0.05) return;
    if (options.keepLoud && speech && level(a, b) > speech * 0.8) return;
    ranges.push([round(a), round(b)]);
  };
  if (words.length) consider(-options.padding, words[0].s);
  for (let i = 1; i < words.length; i++) consider(words[i - 1].e, words[i].s);
  if (words.length) consider(words[words.length - 1].e, duration + options.padding);
  return ranges;
}

export const FILLERS = ["um", "uh", "uhm", "umm", "er", "erm", "ah", "hmm", "mm", "you know", "i mean"];
const plain = (text: string) => text.toLowerCase().replace(/[^\p{L}\p{N}' ]/gu, "").trim();
/** Source ranges covering every filler word or phrase. */
export function findFillers(words: Word[], fillers: string[]): [number, number][] {
  const phrases = fillers
    .map((f) => plain(f).split(/\s+/).filter(Boolean))
    .filter((p) => p.length)
    .sort((a, b) => b.length - a.length);
  const ranges: [number, number][] = [];
  for (let i = 0; i < words.length; i++) {
    const match = phrases.find((p) => p.every((token, k) => words[i + k] && plain(words[i + k].t) === token));
    if (!match) continue;
    ranges.push(wordRange(words, i, i + match.length - 1));
    i += match.length - 1;
  }
  return ranges;
}
/** How many of `ranges` touch the timeline and how many seconds they would remove. */
export function cutSavings(doc: ProjectDocument, asset: string, ranges: [number, number][]) {
  const kept = keptRanges(doc, asset);
  let count = 0,
    seconds = 0;
  for (const [s, e] of ranges) {
    const overlap = kept.reduce((sum, [a, b]) => sum + Math.max(0, Math.min(e, b) - Math.max(s, a)), 0);
    if (overlap > 0.01) {
      count++;
      seconds += overlap;
    }
  }
  return { count, seconds };
}

export const wordText = (doc: ProjectDocument, asset: string, index: number, word: Word) =>
  doc.wordEdits[asset]?.[index] ?? word.t;
export function setWordText(doc: ProjectDocument, asset: string, index: number, text: string): ProjectDocument {
  return {
    ...doc,
    wordEdits: {
      ...doc.wordEdits,
      [asset]: { ...doc.wordEdits[asset], [index]: text.slice(0, 120) },
    },
  };
}

// ------------------------------------------------------------------ captions

export interface TimedWord {
  text: string;
  start: number;
  end: number;
  highlight: false;
}
/** Spoken words of every audible clip, placed on the timeline. Mirrors timeline_words in project_document.py. */
export function timelineWords(doc: ProjectDocument, words: Record<string, Word[]>): TimedWord[] {
  const tracks = new Map(doc.tracks.map((t) => [t.id, t]));
  const result: TimedWord[] = [];
  for (const clip of doc.clips) {
    const track = tracks.get(clip.track)!;
    const list = clip.asset ? words[clip.asset] : undefined;
    if (!list || clip.muted || track.muted || track.kind === "text") continue;
    const edits = doc.wordEdits[clip.asset!] ?? {},
      end = sourceEnd(clip);
    // Words are in time order: jump to the first one inside the clip.
    let lo = 0,
      hi = list.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (list[mid].s < clip.offset) lo = mid + 1;
      else hi = mid;
    }
    for (let i = lo; i < list.length && list[i].s < end; i++) {
      const text = (edits[i] ?? list[i].t).trim();
      if (text)
        result.push({
          text,
          start: clip.start + (list[i].s - clip.offset) / clip.speed,
          end: clip.start + (Math.min(list[i].e, end) - clip.offset) / clip.speed,
          highlight: false,
        });
    }
  }
  return result.sort((a, b) => a.start - b.start);
}
export const captionLines = (doc: ProjectDocument, words: TimedWord[]) =>
  captionGroups(words, doc.captions.wordsPerLine);

const stamp = (time: number, comma: string) => {
  const ms = Math.round(time * 1000);
  const part = (value: number, size = 2) => String(value).padStart(size, "0");
  return `${part(Math.floor(ms / 3600000))}:${part(Math.floor(ms / 60000) % 60)}:${part(Math.floor(ms / 1000) % 60)}${comma}${part(ms % 1000, 3)}`;
};
/** Subtitles for YouTube's own caption track. */
export function toSrt(lines: TimedWord[][]) {
  return lines
    .map(
      (line, i) =>
        `${i + 1}\n${stamp(line[0].start, ",")} --> ${stamp(Math.max(...line.map((w) => w.end)), ",")}\n${line.map((w) => w.text).join(" ")}\n`,
    )
    .join("\n");
}
/** "0:00 Intro" lines for a YouTube description. */
export const chapterText = (chapters: Chapter[]) =>
  [...chapters]
    .sort((a, b) => a.time - b.time)
    .map((c) => `${timecode(c.time)} ${c.title}`)
    .join("\n");
export function timecode(time: number, frames?: number) {
  const s = Math.max(0, time);
  const h = Math.floor(s / 3600),
    m = Math.floor(s / 60) % 60,
    sec = Math.floor(s) % 60;
  const base = h
    ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`
    : `${m}:${String(sec).padStart(2, "0")}`;
  return frames ? `${base}.${String(Math.floor((s % 1) * frames)).padStart(2, "0")}` : base;
}

// ------------------------------------------------------------------ clip properties

/** Changes a clip's speed; it gets shorter or longer and the clips after it on its track follow. */
export function setSpeed(doc: ProjectDocument, id: string, speed: number): ProjectDocument {
  const clip = doc.clips.find((c) => c.id === id);
  if (!clip || !clip.asset || speed === clip.speed) return doc;
  const duration = round(Math.max(MIN, (clip.duration * clip.speed) / speed)),
    delta = duration - clip.duration;
  return {
    ...doc,
    clips: doc.clips.map((c) =>
      c.id === id
        ? { ...c, speed, duration }
        : c.track === clip.track && c.start >= clipEnd(clip) - EPS
          ? { ...c, start: round(c.start + delta) }
          : c,
    ),
  };
}
/** Records the clip's current look at `t` seconds in, replacing a keyframe already there. */
export function setKeyframe(doc: ProjectDocument, id: string, t: number, values?: Partial<Keyframe>): ProjectDocument {
  return patchClips(doc, new Set([id]), (clip) => {
    const at = round(Math.min(Math.max(0, t), clip.duration));
    const key = { ...clipValues(clip, at), ...values, t: at };
    return {
      keys: [...clip.keys.filter((k) => Math.abs(k.t - at) > 0.05), key].sort((a, b) => a.t - b.t),
    };
  });
}
/** Changes how a clip looks at the playhead: its keyframe there when it is animated, the clip itself otherwise. */
export function setLook(
  doc: ProjectDocument,
  id: string,
  time: number,
  values: Partial<Pick<Clip, "x" | "y" | "scale" | "opacity">>,
): ProjectDocument {
  const clip = doc.clips.find((c) => c.id === id);
  if (!clip) return doc;
  return clip.keys.length ? setKeyframe(doc, id, time - clip.start, values) : patchClips(doc, new Set([id]), values);
}
/** Scale at which a picture covers the whole frame instead of fitting inside it. */
export function coverScale(doc: ProjectDocument, asset: Asset) {
  const fit = Math.min(doc.width / asset.width, doc.height / asset.height);
  return Math.max(doc.width / asset.width, doc.height / asset.height) / fit;
}
/** Turns a video clip's sound into its own clip on an audio track, so the two can be edited apart. */
export function detachAudio(doc: ProjectDocument, id: string): ProjectDocument {
  const clip = doc.clips.find((c) => c.id === id);
  const track = doc.tracks.find((t) => t.kind === "audio");
  if (!clip?.asset || !track || trackOf(doc, clip).kind !== "video") return doc;
  const link = clip.link ?? newClip({ track: clip.track }).id;
  const sound = newClip({
    ...clip,
    id: newClip({ track: track.id }).id,
    track: track.id,
    start: freeStart(doc, track.id, clip.start, clip.duration),
    keys: [],
    link,
  });
  return {
    ...doc,
    clips: [...doc.clips.map((c) => (c.id === id ? { ...c, muted: true, link } : c)), sound],
  };
}
export function addTrack(doc: ProjectDocument, kind: Track["kind"]): ProjectDocument {
  const count = doc.tracks.filter((t) => t.kind === kind).length;
  if (doc.tracks.length >= 24) return doc;
  const label = { video: "Video", audio: "Audio", text: "Text" }[kind];
  return {
    ...doc,
    tracks: [
      ...doc.tracks,
      { id: `${kind[0]}${newClip({ track: "x" }).id.slice(0, 6)}`, kind, name: `${label} ${count + 1}`, muted: false, hidden: false, locked: false },
    ],
  };
}
/** Removes an empty track; the last track of a kind and tracks with clips stay. */
export function removeTrack(doc: ProjectDocument, id: string): ProjectDocument {
  const track = doc.tracks.find((t) => t.id === id);
  if (!track || doc.clips.some((c) => c.track === id) || doc.tracks.filter((t) => t.kind === track.kind).length < 2) return doc;
  return { ...doc, tracks: doc.tracks.filter((t) => t.id !== id) };
}

/** An edit proposed by the assistant or over MCP (backend/src/project_ai.py). */
export type ProposedEdit =
  | { kind: "cut"; ranges: { asset: string; start: number; end: number }[]; time: number; seconds: number; text: string; note: string }
  | { kind: "chapter"; time: number; text: string }
  | { kind: "text"; time: number; seconds: number; text: string }
  | { kind: "title" | "description"; text: string };

/** Applies the accepted edits as one change. Proposed chapters replace the chapters already there. */
export function applyEdits(doc: ProjectDocument, edits: ProposedEdit[]): ProjectDocument {
  let next = doc;
  const chapters = edits.filter((e) => e.kind === "chapter");
  if (chapters.length)
    next = { ...next, chapters: chapters.map((c) => ({ time: c.time, title: c.text })).sort((a, b) => a.time - b.time) };
  for (const edit of edits) {
    if (edit.kind === "title") next = { ...next, title: edit.text.slice(0, 200) };
    else if (edit.kind === "description") next = { ...next, description: edit.text };
    else if (edit.kind === "text") {
      const before = new Set(next.clips.map((c) => c.id));
      next = addTextClip(next, edit.time);
      next = {
        ...next,
        clips: next.clips.map((c) =>
          before.has(c.id) || !c.text ? c : { ...c, duration: round(edit.seconds), text: { ...c.text, content: edit.text } },
        ),
      };
    }
  }
  // Cuts go last: they are source ranges, and closing their gaps moves everything placed above.
  for (const edit of edits)
    if (edit.kind === "cut") for (const range of edit.ranges) next = cutSource(next, range.asset, range.start, range.end, "ai");
  return next;
}
