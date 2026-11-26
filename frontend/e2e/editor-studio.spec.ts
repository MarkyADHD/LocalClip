import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { draft } from "../src/lib/editor/document.test-fixture";

const generation = {
  id: "one",
  user_id: "user",
  source_title: "A conversation worth sharing",
  status: "completed",
  source_type: "upload",
  clips_count: 2,
};
const clips = [1, 2].map((n) => ({
  id: `clip${n}`,
  filename: `clip${n}.mp4`,
  clip_order: n,
  duration: 3,
  text: "Hello world today",
  video_url: `/tasks/one/clips/clip${n}/file`,
}));
const mediaPath = path.resolve("test-results/studio-source.mp4");
test.beforeAll(() => {
  mkdirSync(path.dirname(mediaPath), { recursive: true });
  execFileSync("ffmpeg", [
    "-v",
    "error",
    "-y",
    "-f",
    "lavfi",
    "-i",
    "testsrc2=size=640x360:rate=24:duration=3",
    "-f",
    "lavfi",
    "-i",
    "sine=frequency=440:sample_rate=48000:duration=3",
    "-c:v",
    "libx264",
    "-pix_fmt",
    "yuv420p",
    "-c:a",
    "aac",
    "-movflags",
    "+faststart",
    mediaPath,
  ]);
});
async function setup(page: Page, failSave = false) {
  const documents = new Map(
    clips.map((c) => [c.id, { revision: 0, document: structuredClone(draft) }]),
  );
  await page.route("**/api/auth/get-session**", (r) =>
    r.fulfill({
      json: {
        session: {
          id: "session",
          userId: "user",
          expiresAt: "2099-01-01T00:00:00Z",
        },
        user: {
          id: "user",
          name: "Alex",
          email: "alex@example.com",
          emailVerified: true,
        },
      },
    }),
  );
  await page.route("**/api/tasks/one", (r) => r.fulfill({ json: generation }));
  await page.route("**/api/tasks/one/clips", (r) =>
    r.fulfill({ json: { clips } }),
  );
  await page.route("**/api/fonts/*", (r) =>
    r.fulfill({
      body: readFileSync(
        path.resolve(
          "../backend/fonts",
          path.basename(new URL(r.request().url()).pathname) + ".ttf",
        ),
      ),
      contentType: "font/ttf",
    }),
  );
  await page.route(/\/api\/tasks\/one\/clips\/clip[12]\/editor$/, async (r) => {
    const id = r.request().url().includes("clip1") ? "clip1" : "clip2";
    const saved = documents.get(id)!;
    if (r.request().method() === "PATCH") {
      if (failSave)
        return r.fulfill({
          status: 503,
          json: { detail: "Save temporarily unavailable" },
        });
      const body = r.request().postDataJSON();
      if (body.revision !== saved.revision)
        return r.fulfill({
          status: 409,
          json: { detail: "A newer draft exists" },
        });
      documents.set(id, {
        revision: saved.revision + 1,
        document: body.document,
      });
      return r.fulfill({ json: { revision: saved.revision + 1 } });
    }
    return r.fulfill({
      json: {
        status: "ready",
        basis: `${id}.mp4`,
        duration: 3,
        width: 640,
        height: 360,
        fps: 24,
        hasAudio: true,
        waveform: Array.from(
          { length: 160 },
          (_, i) => 0.2 + Math.abs(Math.sin(i)) * 0.6,
        ),
        draft: saved,
        original: draft,
        jobs: [],
      },
    });
  });
  await page.route("**/editor/media/clean.mp4", (r) => {
    const bytes = readFileSync(mediaPath),
      range = r
        .request()
        .headers()
        ["range"]?.match(/bytes=(\d+)-(\d*)/);
    const start = range ? Number(range[1]) : 0,
      end = range && range[2] ? Number(range[2]) : bytes.length - 1;
    return r.fulfill({
      status: range ? 206 : 200,
      body: bytes.subarray(start, end + 1),
      contentType: "video/mp4",
      headers: {
        "Accept-Ranges": "bytes",
        "Content-Length": String(end - start + 1),
        ...(range
          ? { "Content-Range": `bytes ${start}-${end}/${bytes.length}` }
          : {}),
      },
    });
  });
  await page.route("**/editor/media/thumbnails.jpg", (r) =>
    r.fulfill({ status: 404 }),
  );
  await page.goto("/tasks/one/edit?clip=clip1");
  await expect(page.getByLabel("Word 1", { exact: true })).toBeVisible();
  await expect
    .poll(() =>
      page.locator("video").evaluate((v) => (v as HTMLVideoElement).readyState),
    )
    .toBeGreaterThanOrEqual(2);
  return documents;
}

test("drafts survive clip switching and reload, undo restores an edit", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await setup(page);
  await page.getByRole("tab", { name: "Layout" }).click();
  await page.getByRole("slider", { name: "Zoom", exact: true }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(
    page.getByRole("slider", { name: "Zoom", exact: true }),
  ).toHaveAttribute("aria-valuenow", "1.01");
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(
    page.getByRole("slider", { name: "Zoom", exact: true }),
  ).toHaveAttribute("aria-valuenow", "1");
  await page.getByRole("button", { name: "Redo", exact: true }).click();
  await page.getByRole("button", { name: "Edit clip 2", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Edit clip 2", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Edit clip 1", exact: true }).click();
  await page.getByRole("tab", { name: "Layout" }).click();
  await expect(
    page.getByRole("slider", { name: "Zoom", exact: true }),
  ).toHaveAttribute("aria-valuenow", "1.01");
  await page.reload();
  await page.getByRole("tab", { name: "Layout" }).click();
  await expect(
    page.getByRole("slider", { name: "Zoom", exact: true }),
  ).toHaveAttribute("aria-valuenow", "1.01");
  expect(errors).toEqual([]);
});

test("failed saves retain local edits after reload", async ({ page }) => {
  await setup(page, true);
  await page.getByLabel("Word 1", { exact: true }).fill("Changed");
  await expect(
    page.getByRole("alert").filter({ hasText: "Save temporarily unavailable" }),
  ).toContainText("Save temporarily unavailable");
  await page.reload();
  await expect(page.getByLabel("Word 1", { exact: true })).toHaveValue(
    "Changed",
  );
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(page.getByLabel("Word 1", { exact: true })).toHaveValue("Hello");
});

test("splits and restores non-destructively with keyboard and precise trim", async ({
  page,
}) => {
  await setup(page);
  await page.getByLabel("In point seconds").fill("0.25");
  await page.getByLabel("Out point seconds").fill("2.75");
  await page.getByLabel("Word 2", { exact: true }).click();
  await page.getByRole("button", { name: "Split at playhead" }).click();
  await expect(page.getByText("Segment 2", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Restore original", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Restore original", exact: true })
    .click();
  await expect(page.getByText("Segment 2", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("In point seconds")).toHaveValue("0");
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(page.getByText("Segment 2", { exact: true })).toBeVisible();
});

test("background export sends the complete edited document", async ({
  page,
}) => {
  await setup(page);
  let request: Record<string, unknown> | undefined;
  await page.route("**/editor/exports", (r) => {
    request = r.request().postDataJSON();
    return r.fulfill({ json: { id: "job", status: "queued", progress: 0 } });
  });
  await page.getByLabel("Word 1", { exact: true }).fill("Edited");
  await page.getByRole("tab", { name: "Layout" }).click();
  await page.getByRole("radio", { name: "Square", exact: true }).click();
  await page.getByRole("button", { name: "Export", exact: true }).click();
  await expect(page.getByRole("dialog").getByText(/1080 × 1080/)).toBeVisible();
  await page.getByRole("button", { name: "Export clip", exact: true }).click();
  await expect.poll(() => request).toBeTruthy();
  expect(request).toMatchObject({
    basis: "clip1.mp4",
    document: {
      framing: { aspect: "square" },
      words: [{ text: "Edited" }, { text: "world" }, { text: "today" }],
    },
  });
});

test("preview, caption dragging and responsive layout", async ({
  page,
}, info) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  await setup(page);
  await page.getByRole("button", { name: "Play", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Pause", exact: true }),
  ).toBeVisible();
  await page.waitForTimeout(500);
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  const canvas = page.getByLabel("Edited video preview"),
    box = (await canvas.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height * 0.78);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height * 0.6);
  await page.mouse.up();
  await page.getByText("Customise the style").click();
  await expect(
    page.getByRole("slider", { name: "Subtitle vertical position" }),
  ).not.toHaveAttribute("aria-valuenow", "78");
  await page.screenshot({
    path: info.outputPath("studio-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("studio-mobile.png"),
    fullPage: true,
  });
});

test("one switch bleeps every swear word and single words can opt out", async ({
  page,
}) => {
  await setup(page);
  await page.getByLabel("Word 2", { exact: true }).fill("shit");
  await page.getByRole("tab", { name: "Audio" }).click();
  await page.getByRole("switch", { name: "Bleep 1 swear word" }).click();
  await page.getByRole("tab", { name: "Captions" }).click();
  await page.getByLabel("Word 1", { exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Bleep word 1" }),
  ).toHaveAttribute("aria-pressed", "false");
  await page.getByLabel("Word 2", { exact: true }).click();
  const word = page.getByRole("button", { name: "Bleep word 2" });
  await expect(word).toHaveAttribute("aria-pressed", "true");
  await word.click();
  await expect(word).toHaveAttribute("aria-pressed", "false");
});

test("regenerate captions asks before replacing fixed words", async ({
  page,
}) => {
  const documents = await setup(page);
  let ready = false;
  await page.route("**/clips/clip1/editor/captions", (r) => {
    if (r.request().method() === "POST") return r.fulfill({ json: { status: "pending" } });
    const words = [
      { id: "n1", start: 0.2, end: 0.6, text: "brand", highlight: false, speaker: 0 },
      { id: "n2", start: 0.7, end: 1.1, text: "new", highlight: false, speaker: 1 },
    ];
    r.fulfill({ json: ready ? { status: "ready", words } : { status: "pending" } });
    ready = true;
  });
  await page.getByLabel("Word 1", { exact: true }).fill("fixed");
  await page.getByRole("button", { name: "Regenerate" }).click();
  await page.getByRole("button", { name: "Keep my edits" }).click();
  await expect(page.getByLabel("Word 1", { exact: true })).toHaveValue("fixed");
  await page.getByRole("button", { name: "Regenerate" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Regenerate" }).click();
  await expect(page.getByLabel("Word 1", { exact: true })).toHaveValue("brand", { timeout: 10_000 });
  await expect(page.getByLabel("Word 2", { exact: true })).toHaveValue("new");
  await expect
    .poll(() => documents.get("clip1")!.document.words.map((w: { text: string }) => w.text))
    .toEqual(["brand", "new"]);
});

test("layout, caption look, hook title and safe zone", async ({ page }) => {
  await setup(page);
  let request: { document: Record<string, unknown> } | undefined;
  await page.route("**/editor/exports", (r) => {
    request = r.request().postDataJSON();
    return r.fulfill({ json: { id: "job", status: "queued", progress: 0 } });
  });
  // A look sets its entrance and words per line too.
  await page.getByRole("button", { name: "Impact", exact: true }).click();
  await expect(page.getByRole("button", { name: "Impact", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Hype", exact: true }).click();
  await page.getByRole("group", { name: "Caption entrance" }).getByText("pop", { exact: true }).click();
  await page.getByLabel("Hook title").fill("Wait for it");
  await page.getByRole("slider", { name: "Title stays for" }).press("ArrowRight");
  await page.getByRole("tab", { name: "Layout" }).click();
  await page.getByRole("button", { name: "Cam top", exact: true }).click();
  await expect(page.getByLabel("Facecam area")).toBeVisible();
  // Tapping the small facecam picker opens a big one; drawing there sets the facecam.
  await page.getByLabel("Facecam area").click();
  const big = page.getByRole("dialog").getByLabel("Facecam area"),
    area = (await big.boundingBox())!;
  expect(area.width).toBeGreaterThan(600);
  await page.mouse.move(area.x + area.width * 0.5, area.y + area.height * 0.5);
  await page.mouse.down();
  await page.mouse.move(area.x + area.width * 0.75, area.y + area.height * 0.9, { steps: 4 });
  await page.mouse.up();
  await page.getByRole("button", { name: "Done" }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
  await page.getByRole("combobox", { name: "Safe zones" }).click();
  await page.getByRole("option", { name: "TikTok safe zone" }).click();
  await expect(page.getByLabel("TikTok safe zone")).toBeVisible();
  // Trim by dragging the end of the clip on the timeline.
  const handle = page.getByRole("slider", { name: "Trim end" }),
    box = (await handle.boundingBox())!;
  await page.mouse.move(box.x + 4, box.y + 20);
  await page.mouse.down();
  await page.mouse.move(box.x - 200, box.y + 20, { steps: 4 });
  await page.mouse.up();
  await expect(page.getByLabel("Out point seconds")).not.toHaveValue("3");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  await page.getByRole("button", { name: "Export clip", exact: true }).click();
  await expect.poll(() => request).toBeTruthy();
  expect(request!.document).toMatchObject({
    title: "Wait for it",
    titleSeconds: 0.5,
    framing: { layout: "cam_top" },
  });
  expect((request!.document.framing as { cam: Record<string, number> }).cam).toMatchObject({
    x: expect.closeTo(0.5, 2),
    w: expect.closeTo(0.25, 2),
  });
  expect(request!.document).toMatchObject({
    captions: { font: "THEBOLDFONT", uppercase: true, active: true, animation: "pop" },
  });
});

test("a second speaker gets their own caption colour", async ({ page }) => {
  await setup(page);
  await expect(page.getByLabel("Speaker 2 color")).toHaveCount(0);
  // "world today" belongs to someone else: paint from word 2 on.
  await page.getByLabel("Word 2", { exact: true }).click();
  await page.getByRole("button", { name: "Speaker 2 from word 2" }).click();
  await page.getByLabel("Speaker 2 color").fill("#ff00aa");
  await expect(page.getByLabel("Word 3", { exact: true })).toHaveCSS(
    "color",
    "rgb(255, 0, 170)",
  );
  await expect(page.getByLabel("Word 1", { exact: true })).not.toHaveCSS(
    "color",
    "rgb(255, 0, 170)",
  );
  await page.screenshot({ path: "test-results/studio-speakers.png" });
  await expect
    .poll(async () => {
      const saved = await page.evaluate(() =>
        fetch("/api/tasks/one/clips/clip1/editor").then((r) => r.json()),
      );
      return [
        saved.draft.document.words.map((w: { speaker?: number }) => w.speaker ?? 0),
        saved.draft.document.captions.speakerColors?.[0],
      ];
    })
    .toEqual([[0, 1, 1], "#ff00aa"]);
});

test("punch-in, slow motion, sound clean-up and facecam sharpening reach the export", async ({
  page,
}) => {
  await setup(page);
  let request: { document: Record<string, unknown> } | undefined;
  await page.route("**/editor/exports", (r) => {
    request = r.request().postDataJSON();
    return r.fulfill({ json: { id: "job", status: "queued", progress: 0 } });
  });
  const canvas = page.getByLabel("Edited video preview");
  const before = await canvas.screenshot();
  await page.getByRole("tab", { name: "Effects" }).click();
  await page.getByRole("button", { name: "Punch in here", exact: true }).click();
  // The preview zooms while the punch-in is on.
  await expect.poll(async () => (await canvas.screenshot()).equals(before)).toBe(false);
  await page.screenshot({ path: "test-results/studio-punch.png" });
  await page.getByRole("button", { name: "Loudest moment", exact: true }).click();
  await expect(page.getByRole("button", { name: "Remove punch-in" })).toHaveCount(2);
  await page.getByRole("tab", { name: "Audio" }).click();
  await page.getByRole("switch", { name: "Clean up mic noise" }).click();
  await page.getByRole("slider", { name: "Game and music" }).press("Home");
  await page.getByRole("button", { name: "Play this segment in slow motion" }).click();
  // 3 s at half speed.
  await expect(page.getByLabel("Clip timeline")).toContainText("/ 0:06.00");
  await page.getByRole("tab", { name: "Layout" }).click();
  await page.getByRole("button", { name: "Cam top", exact: true }).click();
  await page.getByRole("switch", { name: "Sharpen facecam with AI" }).click();
  await page.getByRole("button", { name: "Export", exact: true }).click();
  await page.getByRole("button", { name: "Export clip", exact: true }).click();
  await expect.poll(() => request).toBeTruthy();
  expect(request!.document).toMatchObject({
    cleanVoice: true,
    gameVolume: 0,
    segments: [{ speed: 0.5 }],
    framing: { layout: "cam_top", sharpCam: true },
  });
  expect((request!.document.punches as unknown[]).length).toBe(2);
});
