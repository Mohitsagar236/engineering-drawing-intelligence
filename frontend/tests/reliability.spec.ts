import { test, expect, type Page } from "@playwright/test";

const drawing = (id: number, status = "COMPLETE") => ({
  id,
  filename: `drawing-${id}.pdf`,
  pages: 2,
  status,
  created_at: "2026-11-05T10:00:00Z",
  project_id: null,
  tags: [],
  job: { id, status, engine: "easyocr", error: "", preprocessing: {} },
});
const result = (id: number, status = "COMPLETE") => ({
  job: drawing(id, status).job,
  pages: [
    { number: 1, width: 100, height: 100 },
    { number: 2, width: 100, height: 100 },
  ],
  findings: [1, 2].map((n) => ({
    id: id * 10 + n,
    page: n,
    source_text: `Annotation ${n}`,
    normalized_name: `Material ${n}`,
    classification: "MANUAL_REVIEW",
    confidence: 0.9,
    bbox: [
      [0, 0],
      [10, 0],
      [10, 10],
      [0, 10],
    ],
    engine: "easyocr",
    is_material: true,
    match_score: 1,
    method: "exact",
    explanation: "Verify source",
    reference: {},
    review: null,
  })),
});
async function mock(page: Page, count = 2, status = "COMPLETE") {
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace("/api", "");
    let body: unknown = {};
    if (path === "/session")
      body = { authenticated: true, authentication_required: true };
    else if (path === "/documents") {
      const offset = Number(url.searchParams.get("offset") || 0);
      body = Array.from({ length: count }, (_, i) =>
        drawing(i + 1, status),
      ).slice(offset, offset + Number(url.searchParams.get("limit") || 100));
    } else if (path === "/dashboard/stats")
      body = {
        documents: count,
        pages: count * 2,
        materials: 0,
        classifications: {},
        categories: {},
        confidence: [],
        processing: {},
      };
    else if (path === "/materials" || path === "/projects" || path === "/tags")
      body = [];
    else if (/\/history$/.test(path))
      body = [drawing(Number(path.split("/")[2]), status).job];
    else if (/\/results$/.test(path))
      body = result(Number(path.split("/")[2]), status);
    else if (/^\/documents\/\d+$/.test(path))
      body = drawing(Number(path.split("/")[2]), status);
    await route.fulfill({ json: body });
  });
}

test("all API document pages are accessible through drawing pagination", async ({
  page,
}) => {
  await mock(page, 201);
  await page.goto("/");
  await expect(page.getByText("201 drawings", { exact: true })).toBeVisible();
  for (let n = 0; n < 8; n++)
    await page.getByRole("button", { name: "Next drawings" }).click();
  await expect(
    page.getByRole("button", { name: "Open drawing-201.pdf", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Next drawings" }),
  ).toBeDisabled();
  await expect(page.getByText("Page 9 / 9", { exact: true })).toBeVisible();
});

test("a delayed result cannot repopulate the viewer after navigation", async ({
  page,
}) => {
  await mock(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/documents/1/results", async (route) => {
    await gate;
    await route.fulfill({ json: result(1) });
  });
  await page.goto("/");
  await page
    .getByRole("button", { name: "Open drawing-1.pdf", exact: true })
    .click();
  await expect(page.getByText("Loading analysis…")).toBeVisible();
  await page.getByRole("button", { name: "Documents", exact: true }).click();
  release();
  await page
    .getByRole("button", { name: "Open drawing-2.pdf", exact: true })
    .click();
  await expect(
    page.getByRole("link", { name: /Download PDF/ }),
  ).toHaveAttribute("href", /documents\/2\/report\?job_id=2/);
});

test("protected 401 clears the workspace and presents sign in", async ({
  page,
}) => {
  await mock(page);
  await page.route("**/api/documents/1/results", (route) =>
    route.fulfill({ status: 401, body: "" }),
  );
  await page.goto("/");
  await page
    .getByRole("button", { name: "Open drawing-1.pdf", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Sign in", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("alert").filter({ hasText: "Session expired" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Material findings" }),
  ).toHaveCount(0);
});

test("failed analysis can be retried without showing stale results", async ({
  page,
}) => {
  await mock(page);
  let failures = 1;
  await page.route("**/api/documents/1/results", (route) =>
    failures-- > 0
      ? route.fulfill({ status: 502, body: "<html>proxy unavailable</html>" })
      : route.fulfill({ json: result(1) }),
  );
  await page.goto("/");
  await page
    .getByRole("button", { name: "Open drawing-1.pdf", exact: true })
    .click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Request failed (502)" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Retry analysis" }).click();
  await expect(page.getByRole("img", { name: "Drawing page 1" })).toBeVisible();
});

test("polling preserves page and zoom while processing", async ({ page }) => {
  await mock(page, 2, "PROCESSING");
  let requests = 0;
  await page.route("**/api/documents/1/results*", async (route) => {
    requests++;
    await route.fulfill({ json: result(1, "PROCESSING") });
  });
  await page.goto("/");
  await page
    .getByRole("button", { name: "Open drawing-1.pdf", exact: true })
    .click();
  await expect(page.getByRole("img", { name: "Drawing page 1" })).toBeVisible();
  await page.getByRole("button", { name: "Next page", exact: true }).click();
  await page.getByRole("button", { name: "Zoom in", exact: true }).click();
  await expect.poll(() => requests).toBeGreaterThan(1);
  await expect(page.getByRole("img", { name: "Drawing page 2" })).toBeVisible();
  await expect(page.getByText("125%", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Run analysis" }),
  ).toBeDisabled();
});

test("review drafts do not transfer to another finding", async ({ page }) => {
  await mock(page);
  await page.goto("/");
  await page
    .getByRole("button", { name: "Open drawing-1.pdf", exact: true })
    .click();
  await page.locator(".finding").first().click();
  await page
    .getByLabel("Reason", { exact: true })
    .fill("Reason for first finding");
  await page.locator(".finding").nth(1).click();
  await expect(page.getByLabel("Reason", { exact: true })).toHaveValue("");
});

test("oversized files are rejected before an upload request is sent", async ({
  page,
}) => {
  await mock(page);
  await page.route("**/api/settings", (route) =>
    route.fulfill({ json: { max_upload_mb: 1 } }),
  );
  let uploads = 0;
  await page.route("**/api/documents/upload", (route) => {
    uploads++;
    return route.fulfill({ status: 413, json: { detail: "Too large" } });
  });
  await page.goto("/");
  await expect(page.getByText("2 drawings", { exact: true })).toBeVisible();
  await page.getByLabel("Upload drawings", { exact: true }).setInputFiles({
    name: "too-large.png",
    mimeType: "image/png",
    buffer: Buffer.alloc(2 * 1024 * 1024),
  });
  await expect(
    page.getByRole("alert").filter({ hasText: "1 MB upload limit" }),
  ).toBeVisible();
  expect(uploads).toBe(0);
});

test("zero materials keeps all 275 transcript OCR rows inspectable", async ({
  page,
}) => {
  await mock(page);
  const data = result(1);
  data.findings = Array.from({ length: 275 }, (_, i) => ({
    ...data.findings[0],
    id: 1000 + i,
    page: i === 274 ? 2 : 1,
    source_text:
      i === 274 ? "Semester total credits" : `Transcript row ${i + 1}`,
    normalized_name: "",
    is_material: false,
    method: "none",
    match_score: 0,
  }));
  await page.route("**/api/documents/1/results*", (route) =>
    route.fulfill({ json: data }),
  );
  await page.goto("/");
  await page
    .getByRole("button", { name: "Open drawing-1.pdf", exact: true })
    .click();
  await expect(page.getByText(/No material findings\. Switch/)).toBeVisible();
  await expect(
    page.getByText(/designed for engineering drawings/),
  ).toBeVisible();
  await expect(page.locator(".finding")).toHaveCount(0);
  await expect(page.locator("svg polygon")).toHaveCount(0);
  await page
    .getByRole("button", { name: "All extracted text", exact: true })
    .click();
  await expect(page.locator(".finding")).toHaveCount(275);
  await expect(page.locator(".finding .badge").first()).toHaveText(
    "Extracted text",
  );
  await expect(
    page.locator(".finding .badge").filter({ hasText: "Manual review" }),
  ).toHaveCount(0);
  await expect(page.locator("svg polygon")).toHaveCount(274);
  await page.getByLabel("Search extracted text").fill("semester");
  await expect(page.locator(".finding")).toHaveCount(1);
  await expect(page.locator("svg polygon")).toHaveCount(0);
  await page.locator(".finding").click();
  await expect(page.getByRole("img", { name: "Drawing page 2" })).toBeVisible();
  await expect(page.locator("svg polygon")).toHaveCount(1);
  await expect(page.locator(".evidence .card-title .badge")).toHaveText(
    "Extracted text",
  );
  await expect(page.locator(".evidence dd").first()).toHaveText(
    "Semester total credits",
  );
  await page.getByLabel("Search extracted text").fill("no such annotation");
  await expect(
    page.getByText(/No extracted text matches your search/),
  ).toBeVisible();
  await expect(page.locator("svg polygon")).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: /Evidence and review/ }),
  ).toHaveCount(0);
  await page.getByLabel("Search extracted text").fill("");
  await page
    .getByRole("button", { name: "Material findings", exact: true })
    .click();
  await expect(page.locator("svg polygon")).toHaveCount(0);
});

test("fuzzy candidates show source text and a suggested reference", async ({
  page,
}) => {
  await mock(page);
  const data = result(1);
  data.findings[0] = {
    ...data.findings[0],
    source_text: "Uncertain annotation",
    normalized_name: "Uncertain annotation",
    method: "fuzzy",
    reference: { standard_name: "Suggested insulation" },
  };
  await page.route("**/api/documents/1/results*", (route) =>
    route.fulfill({ json: data }),
  );
  await page.goto("/");
  await page
    .getByRole("button", { name: "Open drawing-1.pdf", exact: true })
    .click();
  const candidate = page.locator(".finding").first();
  await expect(candidate.getByRole("heading")).toHaveText(
    "Uncertain annotation",
  );
  await expect(candidate).toContainText(
    "Suggested reference: Suggested insulation",
  );
  await expect(candidate).toContainText("not an identified material");
  await candidate.click();
  await expect(page.locator(".evidence")).toContainText(
    "Suggested reference snapshot",
  );
  await expect(page.locator(".evidence")).toContainText(
    "not verified accuracy",
  );
});
