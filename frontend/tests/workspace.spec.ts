import { test, expect } from "@playwright/test";
test.beforeEach(async ({ page }) => {
  if (!process.env.E2E_AUTH_PASSWORD) return;
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill("reviewer");
  await page
    .getByLabel("Password", { exact: true })
    .fill(process.env.E2E_AUTH_PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Drawing intelligence, at a glance." }),
  ).toBeVisible();
});
test("authenticated sessions can sign out", async ({ page }) => {
  test.skip(
    !process.env.E2E_AUTH_PASSWORD,
    "Enable authenticated test environment",
  );
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Sign in", exact: true }),
  ).toBeVisible();
  const response = await page.request.get("/api/documents");
  expect(response.status()).toBe(401);
});
test("dashboard and catalog are backed by the live API", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Drawing intelligence, at a glance." }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Recent drawings" }),
  ).toBeVisible();
  await page.screenshot({ path: "test-results/dashboard.png", fullPage: true });
  await page
    .getByRole("button", { name: "Material database", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Reference catalog" }),
  ).toBeVisible();
  await expect(
    page.getByText("Glass wool insulation", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Processing configuration" }),
  ).toBeVisible();
  await page.screenshot({ path: "test-results/settings.png", fullPage: true });
  expect(errors).toEqual([]);
});
test("drawing findings align with a rendered page and expose reviews", async ({
  page,
}) => {
  await page.goto("/");
  const drawing = page
    .getByRole("row")
    .filter({ hasText: "synthetic-plan.pdf" })
    .filter({ hasText: /COMPLETE/i })
    .first()
    .getByRole("button")
    .first();
  await expect(drawing).toBeVisible();
  await drawing.click();
  await expect(
    page.getByRole("heading", { name: "Material findings" }),
  ).toBeVisible();
  await expect(page.getByRole("img", { name: "Drawing page 1" })).toBeVisible();
  await expect(page.locator("svg polygon")).toHaveCount(3);
  await page.locator(".finding").first().click();
  await expect(
    page.getByRole("heading", { name: "Record a review decision" }),
  ).toBeVisible();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: /Download PDF report/ }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/analysis-\d+\.pdf/);
  await page.screenshot({
    path: "test-results/drawing-viewer.png",
    fullPage: true,
  });
});
test("mobile navigation stays usable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Drawing intelligence, at a glance." }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({ path: "test-results/mobile.png", fullPage: true });
});
