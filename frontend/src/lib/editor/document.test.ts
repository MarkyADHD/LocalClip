import { describe, expect, it } from "vitest";
import {
  captionGroups,
  editDuration,
  frameRect,
  mappedWords,
  outputSize,
  replaceWords,
  splitSegment,
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
    const { isSwear, censor, needsServerExport } = await import("./document");
    expect(["Fucking,", "shit!", "ASSHOLE"].every(isSwear)).toBe(true);
    expect(["class", "assume", "shiitake", "duck"].some(isSwear)).toBe(false);
    expect(censor("Fucking,")).toBe("F******,");
    const doc = {
      words: [{ id: "w", start: 0, end: 1, text: "shit", highlight: false }],
    } as never as Parameters<typeof needsServerExport>[0];
    expect(needsServerExport(doc)).toBe(false);
    expect(
      needsServerExport({ ...doc, words: [{ ...doc.words[0], bleep: true }] }),
    ).toBe(true);
  });
});

describe("layouts and older drafts", () => {
  it("grows the facecam box to the pane's shape and keeps it in frame", async () => {
    const { regionCrop } = await import("./document");
    // A tall box in the corner, shown in a wide pane: widened, pushed back inside the frame.
    const crop = regionCrop({ x: 0, y: 0.5, w: 0.1, h: 0.5 }, 2, 1280, 720);
    expect(crop).toEqual({ x: 0, y: 360, width: 720, height: 360 });
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
    delete (old.framing as Record<string, never>).layout;
    const next = normalize(old as unknown as typeof draft);
    expect(next.title).toBe("");
    expect(next.framing.layout).toBe("crop");
    expect(normalize(next)).toBe(next);
  });
});
