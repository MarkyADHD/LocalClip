export interface Segment {
  id: string;
  start: number;
  end: number;
}
export interface CaptionWord {
  id: string;
  start: number;
  end: number;
  text: string;
  highlight: boolean;
  /** Beep over the word and star it out in the caption. */
  bleep?: boolean;
}
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
  /** Hook title shown at the top for the whole clip; empty for none. */
  title: string;
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
      captions: {
        ...doc.captions,
        uppercase: doc.captions.uppercase ?? false,
        outline: doc.captions.outline ?? 4,
        active: doc.captions.active ?? false,
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
/** Edits only the server can render (the in-browser export keeps the clip's own audio). */
export const needsServerExport = (doc: EditDocument) =>
  doc.words.some((w) => w.bleep);
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
  doc.segments.reduce((total, s) => total + s.end - s.start, 0);
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
      length = s.end - s.start;
    if (time < cursor + length || index === doc.segments.length - 1)
      return { index, time: clamp(s.start + time - cursor, s.start, s.end) };
    cursor += length;
  }
  return { index: 0, time: 0 };
}
export function mappedWords(doc: EditDocument): CaptionWord[] {
  const result: CaptionWord[] = [];
  let cursor = 0;
  const orderedWords = [...doc.words].sort((a, b) => a.start - b.start);
  for (const segment of doc.segments) {
    for (const word of orderedWords) {
      const start = Math.max(segment.start, word.start),
        end = Math.min(segment.end, word.end);
      if (end > start && word.text.trim())
        result.push({
          ...word,
          start: cursor + start - segment.start,
          end: cursor + end - segment.start,
        });
    }
    cursor += segment.end - segment.start;
  }
  return result;
}
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
  return (
    doc.segments
      .slice(0, segmentIndex)
      .reduce((sum, s) => sum + s.end - s.start, 0) +
    sourceTime -
    doc.segments[segmentIndex].start
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
    { id: uid(), start: at, end: segment.end },
  );
  return { ...doc, segments };
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
      });
    }
    if (nextI < words.length) result.push({ ...words[nextI] });
  }
  return result;
}
