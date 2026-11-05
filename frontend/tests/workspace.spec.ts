import { test, expect } from "@playwright/test";
import { crc32, deflateSync } from "node:zlib";

function largePng() {
  const chunk = (name: string, data: Buffer) => {
    const type = Buffer.from(name);
    const size = Buffer.alloc(4);
    size.writeUInt32BE(data.length);
    const checksum = Buffer.alloc(4);
    checksum.writeUInt32BE(crc32(Buffer.concat([type, data])));
    return Buffer.concat([size, type, data, checksum]);
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(2048, 0);
  header.writeUInt32BE(2048, 4);
  header[8] = 8;
  header[9] = 2; // RGB, eight bits per channel.
  const stride = 2048 * 3 + 1;
  const pixels = Buffer.alloc(stride * 2048, 255);
  for (let row = 0; row < 2048; row++) pixels[row * stride] = 0;
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(pixels, { level: 0 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

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

test("CSV import reports imported and skipped references", async ({ page }) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Material database", exact: true })
    .click();
  const csv = {
    name: "references.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(`standard_name\nBrowser import ${Date.now()}\n`),
  };
  const input = page.locator('input[accept=".csv"]');
  await input.setInputFiles(csv);
  await expect(page.getByRole("status")).toContainText(
    "Imported 1 references; skipped 0 existing references",
  );
  await expect(input).toBeEnabled();
  await input.setInputFiles(csv);
  await expect(page.getByRole("status")).toContainText(
    "Imported 0 references; skipped 1 existing references",
  );
});

test("live review persists its evidence and decision", async ({ page }) => {
  await page.goto("/");
  await page
    .getByRole("row")
    .filter({ hasText: "synthetic-plan.pdf" })
    .filter({ hasText: /COMPLETE/i })
    .first()
    .getByRole("button")
    .first()
    .click();
  const reportHref = await page
    .getByRole("link", { name: /Download PDF/ })
    .getAttribute("href");
  const documentId = reportHref!.match(/documents\/(\d+)\//)![1];
  await page.locator(".finding").first().click();
  await page
    .getByLabel("Reason", { exact: true })
    .fill("Browser regression review of synthetic fixture.");
  await page
    .getByLabel("Evidence source", { exact: true })
    .fill("Synthetic drawing fixture generated by scripts/smoke.py.");
  await page.getByRole("button", { name: "Save review", exact: true }).click();
  await expect(page.getByText(/Latest review:/)).toContainText(
    "Browser regression review of synthetic fixture.",
  );
  await page.reload();
  await page
    .getByRole("row")
    .filter({ hasText: `Drawing #${documentId.padStart(4, "0")}` })
    .first()
    .getByRole("button")
    .first()
    .click();
  await page.locator(".finding").first().click();
  await expect(page.getByText(/Latest review:/)).toContainText(
    "Synthetic drawing fixture generated by scripts/smoke.py.",
  );
});

test("invalid drawing upload shows a readable API error and can be retried", async ({
  page,
}) => {
  await page.goto("/");
  const input = page.getByLabel("Upload drawings", { exact: true });
  await input.setInputFiles({
    name: "empty.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from(""),
  });
  await expect(
    page.getByRole("alert").filter({ hasText: "File is empty" }),
  ).toBeVisible();
  await expect(input).toBeEnabled();
  await input.setInputFiles({
    name: "empty.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from(""),
  });
  await expect(
    page.getByRole("alert").filter({ hasText: "File is empty" }),
  ).toBeVisible();
});

test("valid drawings larger than 10 MiB upload through the frontend proxy", async ({
  page,
}) => {
  await page.goto("/");
  const buffer = largePng();
  expect(buffer.length).toBeGreaterThan(10 * 1024 * 1024);
  const upload = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/documents/upload") &&
      response.request().method() === "POST",
  );
  await page.getByLabel("Upload drawings", { exact: true }).setInputFiles({
    name: "large-proxy-regression.png",
    mimeType: "image/png",
    buffer,
  });
  const response = await upload;
  expect(response.status(), await response.text()).toBe(202);
  await expect(page.getByRole("status")).toContainText("Drawings uploaded");
});

test("favicon and declared application icon are available", async ({
  page,
}) => {
  await page.goto("/");
  const icon = page.locator('link[rel="icon"]').first();
  await expect(icon).toHaveAttribute("href", /icon\.svg/);
  const response = await page.request.get("/favicon.ico");
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toContain("image/svg+xml");
});
