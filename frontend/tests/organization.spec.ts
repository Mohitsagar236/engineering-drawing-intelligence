import { test, expect } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  if (!process.env.E2E_AUTH_PASSWORD) return;
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill("reviewer");
  await page
    .getByLabel("Password", { exact: true })
    .fill(process.env.E2E_AUTH_PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
});

test("projects can be created and appear in summaries, filters, and the audit log", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const name = "E2E project " + Date.now();
  await page.goto("/");
  await page.getByRole("button", { name: "Projects", exact: true }).click();
  await page.getByLabel("Name", { exact: true }).fill(name);
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByText("No drawings are assigned")).toBeVisible();
  await expect(
    page.getByRole("img", { name: "Classification counts" }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Documents", exact: true }).click();
  await expect(
    page.getByRole("search", { name: "Filter drawings" }),
  ).toBeVisible();
  await expect(
    page.getByLabel("Filter by project").locator("option", { hasText: name }),
  ).toHaveCount(1);
  await page
    .getByLabel("Search drawings")
    .fill("no-such-drawing-" + Date.now());
  await expect(
    page.getByText("Your drawing workspace starts here."),
  ).toBeVisible();

  await page.getByRole("button", { name: "Audit log", exact: true }).click();
  await page.getByLabel("Filter by action").selectOption("project.create");
  await expect(
    page.getByRole("cell", { name: "project.create" }).first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "Show" }).first().click();
  await expect(page.getByText(name).first()).toBeVisible();
  expect(errors).toEqual([]);
});
