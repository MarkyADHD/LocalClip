import { expect, test } from "@playwright/test";

const generation = { id: "one", user_id: "user", source_title: "A conversation worth sharing", source_type: "youtube", status: "completed", clips_count: 1, created_at: "2026-09-16T10:00:00Z", updated_at: "2026-09-16T10:00:00Z" };
const clip = { id: "clip", filename: "clip.mp4", clip_order: 1, duration: 12, start_time: "00:10", end_time: "00:22", text: "A clear idea deserves a clear explanation.", video_url: "/tasks/one/clips/clip/file", relevance_score: 0.8, virality_score: 75 };

test.beforeEach(async ({ page }) => {
  await page.route("**/api/auth/get-session**", (route) => route.fulfill({ json: { session: { id: "session", userId: "user", expiresAt: "2099-01-01T00:00:00Z" }, user: { id: "user", name: "Alex", email: "alex@example.com", emailVerified: true } } }));
  await page.route("**/api/fonts", (route) => route.fulfill({ json: { fonts: [] } }));
  await page.route("**/api/caption-templates", (route) => route.fulfill({ json: { templates: [{ id: "default", name: "Default", description: "Word captions" }] } }));
  await page.route("**/api/tasks/one", (route) => route.fulfill({ json: generation }));
  await page.route("**/api/tasks/one/clips", (route) => route.fulfill({ json: { clips: [clip] } }));
  await page.route("**/api/tasks/one/clips/clip/file**", (route) => route.fulfill({ status: 404 }));
});


test("results send editing to the selected clip and expose one status badge", async ({ page }) => {
  await page.goto("/tasks/one");
  await expect(page.getByRole("heading", { name: generation.source_title })).toBeVisible();
  await expect(page.getByText("Completed", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Edit", exact: true })).toHaveAttribute("href", "/tasks/one/edit?clip=clip");
  await expect(page.getByPlaceholder("Start trim (sec)")).toHaveCount(0);
  await page.screenshot({ path: "test-results/results-polish.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("generation list refreshes active jobs without losing selection", async ({ page }) => {
  let reads = 0;
  await page.route(/\/api\/tasks\/?$/, (route) => route.fulfill({ json: { tasks: [{ ...generation, status: ++reads <= 2 ? "processing" : "completed" }] } }));
  await page.goto("/list");
  await expect(page.getByText("Processing", { exact: true })).toBeVisible();
  await page.getByRole("checkbox").last().check();
  await expect(page.getByText("Completed", { exact: true })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByRole("checkbox").last()).toBeChecked();
});




test("task completion retries a transient clip-read failure", async ({ page }) => {
  let taskReads = 0;
  let clipReads = 0;
  await page.route("**/api/tasks/one", route => route.fulfill({ json: { ...generation, status: ++taskReads === 1 ? "processing" : "completed" } }));
  await page.route("**/api/tasks/one/clips", route => {
    clipReads++;
    if (clipReads === 2) return route.fulfill({ status: 503, json: { detail: "Temporary clip lookup failure" } });
    return route.fulfill({ json: { clips: clipReads === 1 ? [] : [clip] } });
  });
  await page.route("**/api/tasks/one/progress", route => route.fulfill({ status: 503 }));
  await page.goto("/tasks/one");
  await expect(page.getByText("Completed", { exact: true })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("link", { name: "Edit", exact: true })).toHaveAttribute("href", "/tasks/one/edit?clip=clip");
  expect(taskReads).toBeGreaterThanOrEqual(3);
  expect(clipReads).toBeGreaterThanOrEqual(3);
  await expect(page.getByRole("heading", { name: "Something went wrong" })).toHaveCount(0);
});


test("signed-in settings waits for preferences before showing the form", async ({ page }) => {
  let finish!: () => void;
  let started!: () => void;
  const pending = new Promise<void>(resolve => finish = resolve);
  const loading = new Promise<void>(resolve => started = resolve);
  await page.route("**/api/tasks/billing-summary", route => route.fulfill({ json: { monetization_enabled: false } }));
  await page.route("**/api/preferences", async route => {
    started();
    await pending;
    await route.fulfill({ json: { fontFamily: "TikTokSans-Regular", fontSize: 24, fontColor: "#FFFFFF", notifyOnCompletion: true } });
  });
  await page.goto("/settings");
  await loading;
  await expect(page.getByRole("button", { name: /save preferences/i })).toHaveCount(0);
  finish();
  await expect(page.getByRole("heading", { name: "Caption defaults" })).toBeVisible();
  // Nothing to save until a preference changes.
  await expect(page.getByRole("button", { name: /save preferences/i })).toHaveCount(0);
});

test("settings builds a problem report the user can read before posting it", async ({ page }) => {
  await page.route("**/api/tasks/billing-summary", route => route.fulfill({ json: { monetization_enabled: false } }));
  await page.route("**/api/preferences", route => route.fulfill({ json: { fontFamily: "TikTokSans-Regular", fontSize: 24, fontColor: "#FFFFFF", notifyOnCompletion: true } }));
  await page.route("**/api/problem-report", route => route.fulfill({ json: { report: "**What happened?**\n\n- GPU: NVIDIA GeForce RTX 4070, 12282 MiB\n- AI model: claude-code:sonnet\n\nworker.err.log\nRuntimeError: Claude Code CLI not found." } }));
  await page.goto("/settings");
  await page.getByRole("button", { name: "Report a problem" }).click();
  await expect(page.getByRole("textbox", { name: "Problem report" })).toHaveValue(/RTX 4070[\s\S]*CLI not found/);
  await expect(page.getByRole("link", { name: "Open GitHub and paste" })).toHaveAttribute("href", "https://github.com/MarkyADHD/LocalClip/issues/new");
  if (process.env.SHOT) await page.locator("#help").screenshot({ path: process.env.SHOT });
});

test("font info stays open in a real selector and preserves the selected font", async ({ page }) => {
  await page.route("**/api/fonts", route => route.fulfill({ json: { fonts: [
    { name: "TikTokSans-Regular", display_name: "TikTok Sans Regular", scope: "system", supported_languages: ["en", "pt", "es", "fr", "de", "it", "pl", "tr", "vi", "el", "ru", "uk", "af"] },
    { name: "custom", display_name: "Custom Font", scope: "user", supported_languages: ["hi"] },
  ] } }));
  await page.route("**/api/tasks/billing-summary", route => route.fulfill({ json: { monetization_enabled: false } }));
  await page.route("**/api/preferences", route => route.fulfill({ json: { fontFamily: "TikTokSans-Regular", fontSize: 24, fontColor: "#FFFFFF", notifyOnCompletion: true } }));
  await page.goto("/settings");
  const selector = page.getByRole("combobox").last();
  await selector.click();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("button", { name: "Language support for TikTok Sans Regular" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "TikTok Sans Regular: language support" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("option", { name: "TikTok Sans Regular", exact: true })).toHaveAttribute("data-state", "checked");
  await page.getByRole("button", { name: "Language support for Custom Font" }).click();
  await expect(page.getByRole("heading", { name: "Custom Font: language support" })).toBeVisible();
  await expect(page.getByText(/^Supported:\s*Hindi$/)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("heading", { name: "Custom Font: language support" })).toHaveCount(0);
  await expect(page.getByRole("listbox")).toBeVisible();
  await page.getByRole("option", { name: "Custom Font", exact: true }).click();
  await expect(selector).toHaveText("Custom Font");
  await expect(page.getByRole("button", { name: /save preferences/i })).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await selector.click();
  await page.getByRole("button", { name: "Language support for TikTok Sans Regular" }).click();
  await expect(page.getByRole("heading", { name: "TikTok Sans Regular: language support" })).toBeVisible();
  await page.screenshot({ path: "test-results/font-language-info.png" });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

for (const path of ["/", "/tasks/one"]) {
  test(`font info works inside caption controls at ${path}`, async ({ page }) => {
    await page.route("**/api/fonts", route => route.fulfill({ json: { fonts: [
      { name: "Inter", display_name: "Inter", scope: "system", supported_languages: ["en", "pt"] },
    ] } }));
    await page.route("**/api/tasks/billing-summary", route => route.fulfill({ json: { monetization_enabled: false } }));
    await page.route(/\/api\/tasks\/?(\?.*)?$/, route => route.fulfill({ json: { tasks: [] } }));
    await page.goto(path);
    await page.getByRole("button", { name: path === "/" ? "Default" : "Restyle", exact: true }).click();
    await page.getByRole("combobox").first().click();
    await page.getByRole("button", { name: "Language support for Inter" }).click();
    await expect(page.getByRole("heading", { name: "Inter: language support" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("listbox")).toBeVisible();
    await page.getByRole("option", { name: "Inter", exact: true }).click();
    await expect(page.getByRole("combobox").first()).toHaveText("Inter");
  });
}

test("the Twitch follow bar can be dismissed and stays dismissed", async ({ page }) => {
  await page.route(/\/api\/tasks\/?$/, (route) => route.fulfill({ json: { tasks: [generation] } }));
  await page.goto("/list");
  const bar = page.getByRole("region", { name: "Announcement" });
  const link = bar.getByRole("link", { name: "following me on Twitch" });
  await expect(link).toHaveAttribute("href", "https://twitch.tv/markyadhd");
  await expect(link).toHaveAttribute("target", "_blank");
  await bar.getByRole("button", { name: "Dismiss" }).click();
  await expect(bar).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(bar).toHaveCount(0);
});

test("home shows setup problems; warnings can be hidden, errors cannot", async ({ page }) => {
  await page.route("**/api/tasks/billing-summary", route => route.fulfill({ json: { monetization_enabled: false } }));
  await page.route("**/api/preferences", route => route.fulfill({ json: { fontFamily: "TikTokSans-Regular", fontSize: 24, fontColor: "#FFFFFF", notifyOnCompletion: true } }));
  await page.route(/\/api\/tasks\/?$/, route => route.fulfill({ json: { tasks: [] } }));
  await page.route("**/api/setup-check", route => route.fulfill({ json: { problems: [
    { id: "ai", level: "error", title: "No AI model to pick clips", detail: 'Claude Code is installed but not signed in. Open a terminal, run "claude" and sign in. Or pick a model that runs on this PC (Ollama, LM Studio) in Settings > AI model.', link: "/settings" },
    { id: "gpu", level: "warning", title: "No NVIDIA graphics card found", detail: "LocalClip still works, but transcribing and rendering run on the processor and take much longer." },
  ] } }));
  await page.goto("/");
  const problems = page.getByRole("region", { name: "Setup problems" });
  await expect(problems.getByText("No AI model to pick clips")).toBeVisible();
  await expect(problems.getByRole("link", { name: "Open Settings" })).toHaveAttribute("href", "/settings");
  if (process.env.SHOT) await page.screenshot({ path: process.env.SHOT });
  await problems.getByRole("button", { name: "Hide: No NVIDIA graphics card found" }).click();
  await page.reload();
  await expect(problems.getByText("No AI model to pick clips")).toBeVisible();
  await expect(problems.getByText("No NVIDIA graphics card found")).toHaveCount(0);
});

test("search the stream finds a phrase and clips around it", async ({ page }) => {
  let asked = "";
  let range: unknown;
  await page.route("**/api/tasks/one/transcript/search**", (route) => {
    asked = new URL(route.request().url()).searchParams.get("q") ?? "";
    return route.fulfill({ json: { hits: [
      { start: 1325, end: 1331, label: "22:05", text: "oh my God, he did NOT just do that" },
      { start: 6005, end: 6011, label: "100:05", text: "no way, no way, clip that" },
    ] } });
  });
  await page.route("**/api/tasks/one/clips/from-range", (route) => {
    range = route.request().postDataJSON();
    return route.fulfill({ json: { message: "Task resumed" } });
  });
  await page.goto("/tasks/one");
  await page.getByRole("button", { name: "Search the stream" }).click();
  await page.getByLabel("Words to find").fill("no way");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByRole("list", { name: "Search results" }).getByRole("listitem")).toHaveCount(2);
  expect(asked).toBe("no way");
  if (process.env.SHOT) await page.screenshot({ path: process.env.SHOT });
  await page.getByRole("button", { name: "Clip the moment at 100:05" }).click();
  // 20 seconds before the phrase to 10 seconds after it.
  await expect.poll(() => range).toEqual({ start: 5985, end: 6021 });
  await expect(page.getByRole("dialog")).toBeHidden();
});
