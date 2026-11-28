import { describe, expect, it } from "vitest";
import { popScale } from "./render";
import {
  blurBox,
  captionGroups,
  editDuration,
  frameRect,
  mappedWords,
  outputSize,
  replaceWords,
  paintSpeaker,
  SPEAKER_COLORS,
  speakerCount,
  splitSegment,
  wordColor,
  moveWord,
} from "./document";
import { draft } from "./document.test-fixture";

describe("non-destructive edits", () => {
  it("splits without changing duration or original state", () => {
    const next = splitSegment(draft, 0, 1.1);
    expect(next.segments).toHaveLength(2);
    expect(editDuration(next)).toBeCloseTo(3);
    expect(draft.segments).toHaveLength(1);
    expect(splitSegment(draft, 0, 0.01)).toBe(draft);
  });
  it("maps captions through reordered and duplicated cuts", () => {
    const doc = {
      ...draft,
      segments: [
        { id: "a", start: 1, end: 2 },
        { id: "b", start: 0, end: 1 },
      ],
    };
    const words = mappedWords(doc);
    expect(words.map((w) => [w.text, w.start, w.end])).toEqual([
      ["world", 0, 0.5],
      ["Hello", 1, 1.5],
    ]);
    expect(words[0].highlight).toBe(true);
    expect(captionGroups(words, 1)).toHaveLength(2);
  });
  it("retains downstream word timings after a phrase correction", () => {
    const next = replaceWords(draft.words, "Hello beautiful world today", 3);
    expect(next.find((w) => w.text === "world")).toEqual(draft.words[1]);
    expect(next.find((w) => w.text === "today")).toEqual(draft.words[2]);
    expect(next.every((w) => w.end > w.start && w.end <= 3)).toBe(true);
    expect(replaceWords(draft.words, "Hello earth today", 3)[1]).toMatchObject({
      text: "earth",
      start: 1,
      end: 1.5,
    });
  });
  it("positions crop anchors and preserves original dimensions", () => {
    expect(
      frameRect({ ...draft.framing, x: 0 }, 1920, 1080, 1080, 1920).x,
    ).toBeCloseTo(0);
    const right = frameRect({ ...draft.framing, x: 1 }, 1920, 1080, 1080, 1920);
    expect(right.x + right.width).toBe(1080);
    expect(
      outputSize(
        { ...draft, framing: { ...draft.framing, aspect: "original" } },
        1280,
        720,
      ),
    ).toEqual({ width: 1280, height: 720 });
  });
});

describe("bleep helpers", () => {
  it("finds swears through punctuation and case, not lookalikes", async () => {
    const { isSwear, censor } = await import("./document");
    expect(["Fucking,", "shit!", "ASSHOLE"].every(isSwear)).toBe(true);
    expect(["class", "assume", "shiitake", "duck"].some(isSwear)).toBe(false);
    expect(censor("Fucking,")).toBe("F******,");
  });
});

describe("layouts and older drafts", () => {
  it("grows the facecam box to the pane's shape and keeps it in frame", async () => {
    const { regionCrop } = await import("./document");
    // A tall box in the corner, shown in a wide pane: widened, pushed back inside the frame.
    const crop = regionCrop({ x: 0, y: 0.5, w: 0.1, h: 0.5 }, 2, 1280, 720);
    expect(crop).toEqual({ x: 0, y: 360, width: 720, height: 360 });
  });
  it("keeps a square or tall facecam box as drawn when asked", async () => {
    const { regionCrop } = await import("./document");
    const square = { x: 0.5, y: 0.5, w: 0.25, h: 0.4 }; // 320x288 of 1280x720
    expect(regionCrop(square, 1.4, 1280, 720, true)).toEqual({ x: 640, y: 360, width: 320, height: 288 });
    // A wide box still fills the pane.
    expect(regionCrop({ x: 0, y: 0, w: 0.5, h: 0.2 }, 1.4, 1280, 720, true).height).toBeCloseTo(640 / 1.4);
  });
  it("maps timeline time back to the cut it falls in", async () => {
    const { sourceTime } = await import("./document");
    const doc = {
      ...draft,
      segments: [
        { id: "b", start: 2, end: 3 },
        { id: "a", start: 0, end: 1 },
      ],
    };
    expect(sourceTime(doc, 0.5)).toEqual({ index: 0, time: 2.5 });
    expect(sourceTime(doc, 1.25)).toEqual({ index: 1, time: 0.25 });
    expect(sourceTime(doc, 99)).toEqual({ index: 1, time: 1 });
  });
  it("gives a draft saved by an older version the new defaults", async () => {
    const { normalize } = await import("./document");
    const old = structuredClone(draft) as unknown as Record<string, never>;
    delete old.title;
    delete old.titleSeconds;
    delete (old.framing as Record<string, never>).layout;
    const next = normalize(old as unknown as typeof draft);
    expect(next.title).toBe("");
    expect(next.titleSeconds).toBe(0);
    expect(next.framing.layout).toBe("crop");
    expect(normalize(next)).toBe(next);
  });
});

describe("speakers", () => {
  const words = [0, 0, 1, 1, 0].map((speaker, i) => ({
    id: `w${i}`,
    start: i,
    end: i + 1,
    text: "x",
    highlight: false,
    speaker,
  }));
  it("paints from a word to the next change of speaker", () => {
    expect(paintSpeaker(words, "w1", 2).map((w) => w.speaker)).toEqual([0, 2, 1, 1, 0]);
    expect(paintSpeaker(words, "w2", 0).map((w) => w.speaker)).toEqual([0, 0, 0, 0, 0]);
  });
  it("colours each speaker, the first with the caption colour", () => {
    const style = { color: "#FFFFFF", speakerColors: ["#111111"] };
    expect(speakerCount(words)).toBe(2);
    expect(wordColor(style, {})).toBe("#FFFFFF");
    expect(wordColor(style, { speaker: 1 })).toBe("#111111");
    expect(wordColor(style, { speaker: 2 })).toBe("#FFFFFF");
    expect(wordColor({ color: "#FFFFFF" }, { speaker: 2 })).toBe(SPEAKER_COLORS[1]);
  });
});

describe("slow motion and punch-ins", () => {
  it("maps times through slowed and repeated segments", async () => {
    const { addReplay, editDuration, mapped, outputTime, sourceTime } =
      await import("./document");
    const { draft: fixture } = await import("./document.test-fixture");
    const doc = addReplay(
      { ...fixture, segments: [{ id: "a", start: 0, end: 10 }] },
      0,
      4,
      2,
    );
    expect(doc.segments.map((s) => [s.start, s.end, s.speed ?? 1])).toEqual([
      [0, 4, 1],
      [2, 4, 0.5],
      [4, 10, 1],
    ]);
    expect(editDuration(doc)).toBe(14);
    // 5 s into the edit is a quarter of the way through the half-speed replay.
    expect(sourceTime(doc, 5)).toEqual({ index: 1, time: 2.5 });
    expect(outputTime(doc, 1, 2.5)).toBe(5);
    expect(mapped(doc, [{ start: 3, end: 4 }])).toEqual([
      { start: 3, end: 4 },
      { start: 6, end: 8 },
    ]);
  });
});

it("a popping caption grows past full size and settles on it", () => {
  // Same three sizes as the \fscx tags in editor_document.py's enter_tags.
  expect(popScale(0)).toBeCloseTo(0.6);
  expect(popScale(0.6)).toBeCloseTo(1.12);
  expect(popScale(1)).toBeCloseTo(1);
});

describe("blurBox", () => {
  const blur = {
    id: "v",
    label: "Vape",
    start: 0,
    end: 1,
    boxes: [
      { t: 0, x: 0.1, y: 0.1, w: 0.2, h: 0.2 },
      { t: 0.25, x: 0.3, y: 0.2, w: 0.2, h: 0.2 },
    ],
  };
  it("covers the motion between sightings and stops at the end (box_at in auto_blur.py)", () => {
    const box = blurBox(blur, 0.1)!;
    expect([box.x, box.y, box.w, box.h].map((v) => +v.toFixed(3))).toEqual([0.1, 0.1, 0.4, 0.3]);
    expect(blurBox(blur, 0.9)).toEqual({ x: 0.3, y: 0.2, w: 0.2, h: 0.2 });
    expect(blurBox(blur, 1)).toBeNull();
  });
});

describe("moveWord", () => {
  const words = [
    { id: "a", start: 0, end: 1, text: "a", highlight: false },
    { id: "b", start: 2, end: 3, text: "b", highlight: false },
    { id: "c", start: 4, end: 5, text: "c", highlight: false },
  ];
  const times = (list: typeof words) => list.map((w) => [w.start, w.end]);
  it("moves one word without passing its neighbours", () => {
    expect(times(moveWord(words, "b", 0.5, "move", 10))).toEqual([[0, 1], [2.5, 3.5], [4, 5]]);
    expect(times(moveWord(words, "b", 5, "move", 10))[1]).toEqual([3, 4]);
    expect(times(moveWord(words, "b", -5, "move", 10))[1]).toEqual([1, 2]);
  });
  it("moves later words along, up to the end of the clip", () => {
    expect(times(moveWord(words, "b", 0.5, "move", 10, true))).toEqual([[0, 1], [2.5, 3.5], [4.5, 5.5]]);
    expect(times(moveWord(words, "b", 9, "move", 6, true))).toEqual([[0, 1], [3, 4], [5, 6]]);
  });
  it("stretches an edge", () => {
    expect(times(moveWord(words, "b", -0.4, "start", 10))[1]).toEqual([1.6, 3]);
    expect(times(moveWord(words, "b", 2, "end", 10))[1]).toEqual([2, 4]);
    expect(times(moveWord(words, "b", -2, "end", 10))[1]).toEqual([2, 2.05]);
  });
});
