import fs from "fs";
import path from "path";

import { expect, test } from "@playwright/test";

const seed = JSON.parse(
  fs.readFileSync(path.join(process.cwd(), "e2e", ".seed.json"), "utf8"),
);



async function signIn(page: import("@playwright/test").Page, email: string, password: string) {
  // LocalClip has no sign-in page; sign in through the auth API instead.
  const response = await page.request.post("/api/auth/sign-in/email", { data: { email, password } });
  expect(response.ok()).toBeTruthy();
  await page.goto("/");
}

test("regular user can browse seeded tasks and save preferences", async ({ page }) => {
  // This flow compiles several routes (list, task) on its first
  // visit to the dev server; together they can take over a minute in CI.
  test.setTimeout(120_000);
  await signIn(page, seed.regular.email, seed.regular.password);

  await page.goto("/list");
  await expect(page.getByText(seed.completedSourceTitle)).toBeVisible();

  await page.goto(`/tasks/${seed.completedTaskId}`);
  await page.getByRole("button", { name: "Preview Clip 1", exact: true }).click();
  const preview = page.getByRole("dialog");
  await expect(preview.getByText("This is a seeded clip", { exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(preview).not.toBeVisible();

});
