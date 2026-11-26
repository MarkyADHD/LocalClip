export interface Segment {
  id: string;
  start: number;
  end: number;
  /** Below 1 plays the segment in slow motion (0.25 to 1). */
  speed?: number;
}
/** A snap zoom on the picture between two source times. */
export interface Punch {
  id: string;
  start: number;
  end: number;
}
/** How far a punch-in zooms; same in editor_document.py. */
export const PUNCH_ZOOM = 1.25;
/** Height of the point a punch-in zooms towards: the face, or the facecam pane. Same in editor_document.py. */
export const PUNCH_Y = { crop: 0.4, cam_top: 0.2, cam_bottom: 0.8, floating: 0.3 };
/** Seconds a segment lasts in the edited clip. */
export const segmentLength = (s: Segment) => (s.end - s.start) / (s.speed ?? 1);
export interface CaptionWord {
  id: string;
  start: number;
  end: number;
  text: string;
  highlight: boolean;
  /** Beep over the word and star it out in the caption. */
  bleep?: boolean;
  /** Who says it: 0 talks most. Picks the caption colour. */
  speaker?: number;
}
export type CaptionAnimation = "none" | "pop" | "fade" | "slide";
export interface CaptionStyle {
  enabled: boolean;
  font: keyof typeof CAPTION_FONTS;
  size: number;
  color: string;
  accent: string;
  y: number;
  background: boolean;
  wordsPerLine: number;
  uppercase: boolean;
  /** Outline thickness as a percentage of the font size (unused with a text background). */
  outline: number;
  /** Colour the word being spoken with the highlight colour. */
  active: boolean;
  /** How each caption comes in (older drafts have none). */
  animation?: CaptionAnimation;
  /** Colours of speakers 1, 2, ... (speaker 0 uses `color`). */
  speakerColors?: string[];
}
/** Caption colours for the 2nd, 3rd, ... speaker; same in backend/src/media/diarization.py. */
export const SPEAKER_COLORS = ["#38BDF8", "#F472B6", "#4ADE80", "#FB923C", "#A78BFA"];
export const wordColor = (
  style: Pick<CaptionStyle, "color" | "speakerColors">,
  word: Pick<CaptionWord, "speaker">,
) => (word.speaker && (style.speakerColors ?? SPEAKER_COLORS)[word.speaker - 1]) || style.color;
/** How many speakers the clip's words name (at least one). */
export const speakerCount = (words: CaptionWord[]) =>
  Math.max(0, ...words.map((w) => w.speaker ?? 0)) + 1;
/** Gives `speaker` to a word and the words after it, up to the next change of speaker. */
export function paintSpeaker(words: CaptionWord[], id: string, speaker: number) {
  const from = words.findIndex((w) => w.id === id);
  if (from < 0) return words;
  const was = words[from].speaker ?? 0;
  let to = from;
  while (to < words.length && (words[to].speaker ?? 0) === was) to++;
  return words.map((w, i) => (i >= from && i < to ? { ...w, speaker } : w));
}
/** Bundled caption fonts (file stems in backend/fonts); keep in sync with editor_document.py. */
export const CAPTION_FONTS = {
  "TikTokSans-Regular": "TikTok Sans",
  "TikTokSans-Bold": "TikTok Sans Bold",
  "Poppins-ExtraBold": "Poppins Extra Bold",
  THEBOLDFONT: "The Bold Font",
  "Anton-Regular": "Anton",
  "BebasNeue-Regular": "Bebas Neue",
  "ArchivoBlack-Regular": "Archivo Black",
  "Bangers-Regular": "Bangers",
} as const;
/** A region of the source frame, normalised 0..1. */
export interface Region {
  x: number;
  y: number;
  w: number;
  h: number;
}
export interface Framing {
  aspect: "vertical" | "square" | "original";
  fit: "contain" | "cover";
  zoom: number;
  x: number;
  y: number;
  /** crop: one crop of the frame. The others stack or float the facecam (`cam`) with the gameplay. */
  layout: "crop" | "cam_top" | "cam_bottom" | "floating";
  cam: Region;
  /** AI-upscale the facecam for the export (slow; server export). */
  sharpCam?: boolean;
}
export interface Effects {
  brightness: number;
  contrast: number;
  saturation: number;
  blur: number;
  hue: number;
}
export interface EditDocument {
  version: 1;
  segments: Segment[];
  words: CaptionWord[];
  captions: CaptionStyle;
  framing: Framing;
  effects: Effects;
  volume: number;
  muted: boolean;
  /** Hook title shown at the top; empty for none. */
  title: string;
  /** Seconds the title stays up from the start; 0 for the whole clip. */
  titleSeconds: number;
  /** Take rumble and steady hiss out of the sound (server export). */
  cleanVoice: boolean;
  punches: Punch[];
  /** Game and music under the voice (0 to 2); 1 leaves the mix alone (server export). */
  gameVolume: number;
}
const DEFAULT_CAM: Region = { x: 0, y: 0.6, w: 0.3, h: 0.4 };
const normalized = new WeakMap<EditDocument, EditDocument>();
/** Drafts saved before a field existed load with its default (same defaults as the server model). */
export function normalize(doc: EditDocument): EditDocument {
  let result = normalized.get(doc);
  if (!result) {
    result = {
      ...doc,
      title: doc.title ?? "",
      titleSeconds: doc.titleSeconds ?? 0,
      cleanVoice: doc.cleanVoice ?? false,
      punches: doc.punches ?? [],
      gameVolume: doc.gameVolume ?? 1,
      captions: {
        ...doc.captions,
        uppercase: doc.captions.uppercase ?? false,
        outline: doc.captions.outline ?? 4,
        active: doc.captions.active ?? false,
        animation: doc.captions.animation ?? "none",
        speakerColors: doc.captions.speakerColors ?? SPEAKER_COLORS,
      },
      framing: {
        ...doc.framing,
        layout: doc.framing.layout ?? "crop",
        cam: doc.framing.cam ?? DEFAULT_CAM,
      },
    };
    normalized.set(doc, result);
    normalized.set(result, result);
  }
  return result;
}
export interface ExportJob {
  id: string;
  status: "queued" | "rendering" | "completed" | "failed" | "cancelled";
  progress: number;
  error?: string;
}
export interface EditorState {
  status: "unprepared" | "preparing" | "ready" | "failed";
  basis: string;
  error?: string;
  duration: number;
  width: number;
  height: number;
  fps: number;
  hasAudio: boolean;
  waveform: number[];
  draft: { revision: number; document: EditDocument };
  original: EditDocument;
  jobs: ExportJob[];
}
// ponytail: a short English list; per-word toggles in the Captions tab cover anything it misses.
const SWEARS =
  /^(fuck\w*|motherfuck\w*|shit\w*|bullshit|bitch\w*|cunts?|dick(head)?s?|cocks?|puss(y|ies)|ass(hole)?s?|bastards?|pricks?|twats?|wank\w*|slut\w*|whores?|goddamn\w*|damn(ed)?|piss(ed|ing)?|crap)$/i;
export const isSwear = (text: string) =>
  SWEARS.test(text.replace(/[^\p{L}]/gu, ""));
/** f*** : keep the first letter of each word, star the rest (same as the export). */
export const censor = (text: string) =>
  text.replace(/(?<=[\p{L}\p{N}_])[\p{L}\p{N}_]/gu, "*");
export const DEFAULT_EFFECTS: Effects = {
  brightness: 100,
  contrast: 100,
  saturation: 100,
  blur: 0,
  hue: 0,
};
export const clamp = (value: number, min: number, max: number) =>
  Math.min(max, Math.max(min, value));
export const editDuration = (doc: EditDocument) =>
  doc.segments.reduce((total, s) => total + segmentLength(s), 0);
export const timecode = (time: number) =>
  `${Math.floor(Math.max(0, time) / 60)}:${(Math.max(0, time) % 60).toFixed(2).padStart(5, "0")}`;
export const uid = () => crypto.randomUUID();
export function outputSize(doc: EditDocument, width: number, height: number) {
  if (doc.framing.aspect === "vertical") return { width: 1080, height: 1920 };
  if (doc.framing.aspect === "square") return { width: 1080, height: 1080 };
  const scale = Math.min(1, 1920 / Math.max(width, height));
  return {
    width: Math.max(2, Math.floor((width * scale) / 2) * 2),
    height: Math.max(2, Math.floor((height * scale) / 2) * 2),
  };
}
export function frameRect(
  frame: Framing,
  sw: number,
  sh: number,
  width: number,
  height: number,
) {
  const scale =
    (frame.fit === "cover" ? Math.max : Math.min)(width / sw, height / sh) *
    frame.zoom;
  const w = Math.round((sw * scale) / 2) * 2,
    h = Math.round((sh * scale) / 2) * 2;
  return {
    x: (width - w) * frame.x,
    y: (height - h) * frame.y,
    width: w,
    height: h,
  };
}
/** The source pixels shown for `region` in a pane of the given aspect: grown around its centre, kept in frame. */
export function regionCrop(
  region: Region,
  aspect: number,
  sw: number,
  sh: number,
) {
  let w = region.w * sw,
    h = region.h * sh;
  if (w / h < aspect) w = h * aspect;
  else h = w / aspect;
  if (w > sw) [w, h] = [sw, sw / aspect];
  if (h > sh) [w, h] = [sh * aspect, sh];
  return {
    x: clamp((region.x + region.w / 2) * sw - w / 2, 0, sw - w),
    y: clamp((region.y + region.h / 2) * sh - h / 2, 0, sh - h),
    width: w,
    height: h,
  };
}
/** Maps a time on the edited timeline back to its segment and source time. */
export function sourceTime(doc: EditDocument, time: number) {
  let cursor = 0;
  for (let index = 0; index < doc.segments.length; index++) {
    const s = doc.segments[index],
      length = segmentLength(s);
    if (time < cursor + length || index === doc.segments.length - 1)
      return {
        index,
        time: clamp(s.start + (time - cursor) * (s.speed ?? 1), s.start, s.end),
      };
    cursor += length;
  }
  return { index: 0, time: 0 };
}
/** Items with source times, moved onto the edited timeline (cut, repeated, slowed). */
export function mapped<T extends { start: number; end: number }>(
  doc: EditDocument,
  items: T[],
): T[] {
  const result: T[] = [];
  let cursor = 0;
  const ordered = [...items].sort((a, b) => a.start - b.start);
  for (const segment of doc.segments) {
    const speed = segment.speed ?? 1;
    for (const item of ordered) {
      const start = Math.max(segment.start, item.start),
        end = Math.min(segment.end, item.end);
      if (end > start)
        result.push({
          ...item,
          start: cursor + (start - segment.start) / speed,
          end: cursor + (end - segment.start) / speed,
        });
    }
    cursor += segmentLength(segment);
  }
  return result;
}
/**
 * A caption word dragged by `delta` source seconds: the whole word ("move") or one edge.
 * `following` moves every later word with it, to fix captions that drift late or early.
 * Words never pass their neighbours or the ends of the clip.
 */
export function moveWord(
  words: CaptionWord[],
  id: string,
  delta: number,
  edge: "move" | "start" | "end",
  duration: number,
  following = false,
): CaptionWord[] {
  const sorted = [...words].sort((a, b) => a.start - b.start),
    i = sorted.findIndex((w) => w.id === id);
  if (i < 0) return words;
  const word = sorted[i],
    min = Math.min(word.start, sorted[i - 1]?.end ?? 0),
    max = Math.max(word.end, sorted[i + 1]?.start ?? duration),
    round = (t: number) => Math.round(t * 1000) / 1000;
  if (edge !== "move") {
    const changed =
      edge === "start"
        ? { start: round(clamp(word.start + delta, min, word.end - 0.05)) }
        : { end: round(clamp(word.end + delta, word.start + 0.05, max)) };
    return words.map((w) => (w.id === id ? { ...w, ...changed } : w));
  }
  const moving = new Set(following ? sorted.slice(i).map((w) => w.id) : [id]),
    lastEnd = following ? Math.max(...sorted.slice(i).map((w) => w.end)) : word.end,
    shift = clamp(delta, min - word.start, (following ? Math.max(lastEnd, duration) : max) - lastEnd);
  return words.map((w) =>
    moving.has(w.id)
      ? { ...w, start: round(w.start + shift), end: round(w.end + shift) }
      : w,
  );
}
export const mappedWords = (doc: EditDocument): CaptionWord[] =>
  mapped(
    doc,
    doc.words.filter((w) => w.text.trim()),
  );
export function captionGroups<T extends { start: number; end: number }>(
  words: T[],
  count: number,
) {
  const groups: T[][] = [];
  let group: T[] = [];
  for (const word of words) {
    if (
      group.length &&
      (group.length >= count || word.start - group[group.length - 1].end > 0.6)
    ) {
      groups.push(group);
      group = [];
    }
    group.push(word);
  }
  if (group.length) groups.push(group);
  return groups;
}
export function outputTime(
  doc: EditDocument,
  segmentIndex: number,
  sourceTime: number,
) {
  const segment = doc.segments[segmentIndex];
  return (
    doc.segments
      .slice(0, segmentIndex)
      .reduce((sum, s) => sum + segmentLength(s), 0) +
    (sourceTime - segment.start) / (segment.speed ?? 1)
  );
}
export function splitSegment(
  doc: EditDocument,
  index: number,
  at: number,
): EditDocument {
  const segment = doc.segments[index];
  if (!segment || at - segment.start < 0.04 || segment.end - at < 0.04)
    return doc;
  const segments = [...doc.segments];
  segments.splice(
    index,
    1,
    { ...segment, end: at },
    { ...segment, id: uid(), start: at },
  );
  return { ...doc, segments };
}
/** Plays the `seconds` before `at` again at half speed, right after they happen. */
export function addReplay(
  doc: EditDocument,
  index: number,
  at: number,
  seconds = 2.5,
): EditDocument {
  const segment = doc.segments[index];
  if (!segment) return doc;
  at = clamp(at, segment.start + 0.04, segment.end);
  const replay = {
    id: uid(),
    start: Math.max(segment.start, at - seconds),
    end: at,
    speed: 0.5,
  };
  const split = splitSegment(doc, index, at);
  const segments = [...split.segments];
  segments.splice(index + 1, 0, replay);
  return { ...doc, segments };
}
/** The loudest moment that is kept in the edit and has no punch-in near it, as a source time. */
export function loudestMoment(doc: EditDocument, waveform: number[], duration: number) {
  let best: number | null = null,
    peak = -1;
  waveform.forEach((level, i) => {
    const at = ((i + 0.5) / waveform.length) * duration;
    if (
      level > peak &&
      doc.segments.some((s) => at >= s.start && at < s.end) &&
      !doc.punches.some((p) => at >= p.start - 1 && at <= p.end + 1)
    )
      [best, peak] = [at, level];
  });
  return best as number | null;
}
/** Correcting a phrase retains existing time anchors; inserted words share only the replaced span. */
export function replaceWords(
  words: CaptionWord[],
  text: string,
  duration: number,
): CaptionWord[] {
  const tokens = text.trim().split(/\s+/).filter(Boolean);
  // LCS anchors preserve unchanged words, including those after an insertion/deletion.
  const rows = words.length + 1,
    cols = tokens.length + 1;
  if (rows * cols > 1_000_000)
    throw new Error("Edit this long transcript one word at a time.");
  const table = Array.from({ length: rows }, () => new Uint16Array(cols));
  for (let i = words.length - 1; i >= 0; i--)
    for (let j = tokens.length - 1; j >= 0; j--)
      table[i][j] =
        words[i].text === tokens[j]
          ? table[i + 1][j + 1] + 1
          : Math.max(table[i + 1][j], table[i][j + 1]);
  const anchors: [number, number][] = [[-1, -1]];
  let i = 0,
    j = 0;
  while (i < words.length && j < tokens.length) {
    if (words[i].text === tokens[j]) {
      anchors.push([i++, j++]);
    } else if (table[i + 1][j] >= table[i][j + 1]) i++;
    else j++;
  }
  anchors.push([words.length, tokens.length]);
  const result: CaptionWord[] = [];
  for (let k = 1; k < anchors.length; k++) {
    const [prevI, prevJ] = anchors[k - 1],
      [nextI, nextJ] = anchors[k];
    const count = nextJ - prevJ - 1;
    const start =
      nextI > prevI + 1 ? words[prevI + 1].start : (words[prevI]?.end ?? 0);
    const end =
      nextI > prevI + 1
        ? words[nextI - 1].end
        : (words[nextI]?.start ?? duration);
    for (let n = 0; n < count; n++) {
      const from = start + (Math.max(0.01, end - start) * n) / count;
      result.push({
        id: uid(),
        text: tokens[prevJ + n + 1].slice(0, 120),
        start: clamp(from, 0, duration - 0.01),
        end: clamp(
          start + (Math.max(0.01, end - start) * (n + 1)) / count,
          from + 0.001,
          duration,
        ),
        highlight: false,
        speaker: (words[prevI + 1] ?? words[prevI] ?? words[nextI])?.speaker,
      });
    }
    if (nextI < words.length) result.push({ ...words[nextI] });
  }
  return result;
}
