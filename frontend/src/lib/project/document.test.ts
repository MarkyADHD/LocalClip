import { describe, expect, it } from "vitest";
import {
  addAssetClip,
  applyEdits,
  clipEnd,
  cutRanges,
  cutSavings,
  cutSource,
  deleteClips,
  docDuration,
  findFillers,
  findSilences,
  keptRanges,
  keptWords,
  moveClips,
  restoreCuts,
  splitAt,
  timelineWords,
  toSrt,
  trimClip,
  type Asset,
  type ProjectDocument,
  type Word,
} from "./document";

const video: Asset = {
  id: "vid", name: "stream.mp4", kind: "video", status: "ready", progress: 100,
  duration: 100, width: 2560, height: 1440, fps: 60, hasAudio: true,
};
const empty: ProjectDocument = {
  version: 1, width: 1920, height: 1080, fps: 30,
  tracks: [
    { id: "v1", kind: "video", name: "Main", muted: false, hidden: false, locked: false },
    { id: "v2", kind: "video", name: "Overlay", muted: false, hidden: false, locked: false },
    { id: "a1", kind: "audio", name: "Music", muted: false, hidden: false, locked: false },
  ],
  clips: [],
  captions: {
    enabled: true, font: "Poppins-ExtraBold", size: 30, color: "#FFFFFF", accent: "#FACC15",
    y: 0.88, background: true, wordsPerLine: 3, uppercase: false, outline: 4, active: false,
  },
  wordEdits: {}, cuts: [], chapters: [], title: "", description: "",
};
const doc = addAssetClip(empty, video);
const words: Word[] = [
  { s: 1, e: 1.4, t: "Hello" }, { s: 1.5, e: 1.9, t: "um" }, { s: 2, e: 2.5, t: "everyone" },
  { s: 6, e: 6.4, t: "you" }, { s: 6.5, e: 6.9, t: "know" }, { s: 7, e: 7.5, t: "welcome" },
];

describe("project document", () => {
  it("takes its shape from the first video", () => {
    expect([doc.width, doc.height, doc.fps]).toEqual([2560, 1440, 60]);
    expect(doc.clips).toHaveLength(1);
    expect(docDuration(doc)).toBe(100);
  });

  it("cuts a source range, closes the gap and restores it", () => {
    const overlay = { ...doc.clips[0], id: "late", track: "v2", start: 50, duration: 5 };
    const cut = cutSource({ ...doc, clips: [...doc.clips, overlay] }, "vid", 10, 20);
    const main = cut.clips.filter((c) => c.track === "v1");
    expect(main.map((c) => [c.start, c.duration, c.offset])).toEqual([[0, 10, 0], [10, 80, 20]]);
    expect(cut.clips.find((c) => c.id === "late")!.start).toBe(40);
    expect(keptRanges(cut, "vid")).toEqual([[0, 10], [20, 100]]);
    const back = restoreCuts(cut, () => true);
    expect(back.cuts).toHaveLength(0);
    expect(back.clips.filter((c) => c.track === "v1").map((c) => [c.start, c.duration, c.offset])).toEqual([[0, 100, 0]]);
    expect(back.clips.find((c) => c.id === "late")!.start).toBe(50);
  });

  it("applies many cuts and undoes only one kind", () => {
    const silences = findSilences(words, 100, { minPause: 1, padding: 0.1, keepLoud: false });
    expect(silences).toEqual([[0, 0.9], [2.6, 5.9], [7.6, 100]]);
    const fillers = findFillers(words, ["um", "you know"]);
    expect(fillers).toHaveLength(2);
    expect(cutSavings(doc, "vid", silences).count).toBe(3);
    let next = cutRanges(doc, "vid", silences, "silence");
    next = cutRanges(next, "vid", fillers, "filler");
    expect(docDuration(next)).toBeCloseTo(1.85, 2); // Hello, everyone, welcome and a little air
    // Clips stay back to back on the main track.
    const main = next.clips.sort((a, b) => a.start - b.start);
    main.slice(1).forEach((c, i) => expect(c.start).toBeCloseTo(clipEnd(main[i]), 2));
    expect([...keptWords(words, keptRanges(next, "vid"))]).toEqual([1, 0, 1, 0, 0, 1]);
    expect(toSrt([timelineWords(next, { vid: words })])).toContain("Hello everyone welcome");
    const speechOnly = restoreCuts(next, (c) => c.reason === "silence");
    expect(speechOnly.cuts.every((c) => c.reason === "filler")).toBe(true);
    expect(docDuration(speechOnly)).toBeCloseTo(100 - 0.5 - 1.05, 1);
  });

  it("keeps loud pauses when asked", () => {
    const wave = new Uint8Array(2000).fill(200);
    wave.fill(5, 52, 118); // quiet between 2.6 s and 5.9 s
    const found = findSilences(words, 100, { minPause: 1, padding: 0.1, keepLoud: true }, wave, 20);
    expect(found).toEqual([[2.6, 5.9]]);
  });

  it("splits, trims, moves and ripple-deletes", () => {
    let next = splitAt(doc, 30, new Set());
    expect(next.clips.map((c) => [c.start, c.duration, c.offset])).toEqual([[0, 30, 0], [30, 70, 30]]);
    const [a, b] = next.clips;
    next = trimClip(next, b.id, "start", 10, { vid: video });
    expect(next.clips[1].start).toBe(30); // cannot run into its neighbour
    next = trimClip(next, a.id, "end", 20, { vid: video });
    next = trimClip(next, b.id, "start", 25, { vid: video });
    expect(next.clips[1]).toMatchObject({ start: 25, offset: 25, duration: 75 });
    next = moveClips(next, new Set([b.id]), -20, b.id);
    expect(next.clips[1].start).toBe(20); // lands after the first clip, never on top of it
    next = deleteClips(next, new Set([a.id]), true);
    expect(next.clips.map((c) => c.start)).toEqual([0]);
  });

  it("applies accepted assistant edits in one go", () => {
    const withText = { ...doc, tracks: [...doc.tracks, { id: "t1", kind: "text" as const, name: "Text", muted: false, hidden: false, locked: false }] };
    const next = applyEdits(withText, [
      { kind: "cut", ranges: [{ asset: "vid", start: 10, end: 20 }], time: 10, seconds: 10, text: "", note: "" },
      { kind: "chapter", time: 30, text: "Later" },
      { kind: "chapter", time: 0, text: "Intro" },
      { kind: "text", time: 2, seconds: 3, text: "Hi" },
      { kind: "title", text: "A title" },
    ]);
    expect(docDuration(next)).toBeCloseTo(90);
    expect(next.cuts).toMatchObject([{ asset: "vid", start: 10, end: 20, reason: "ai" }]);
    expect(next.title).toBe("A title");
    expect(next.chapters.map((c) => c.title)).toEqual(["Intro", "Later"]);
    // The chapter after the cut moved with the video; the text before it stayed.
    expect(next.chapters[1].time).toBeCloseTo(20);
    expect(next.clips.find((c) => c.text)).toMatchObject({ start: 2, duration: 3, text: { content: "Hi" } });
  });
});
