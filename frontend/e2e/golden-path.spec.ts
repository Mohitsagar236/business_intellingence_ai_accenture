import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";

/**
 * Drives the app end-to-end against the live backend, seeded via
 * `python backend/scripts/seed_and_run.py`. Covers login, the golden path (a validated
 * report), the genuinely-ambiguous path, and the two audit-facing pages — the same
 * walkthrough used to manually verify the app during development, now a regression check.
 */

async function loginAs(page: Page, username: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

test("unauthenticated visitors are redirected to the login page", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
});

test("wrong credentials show an error and do not log in", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("wrong-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Invalid username or password")).toBeVisible();
  await expect(page).toHaveURL(/\/login$/);
});

test("dashboard shows every KPI with a real status, not a placeholder", async ({ page }) => {
  await loginAs(page, "admin", "admin123");

  const cards = page.locator(".kpi-card");
  await expect(cards).toHaveCount(5);
  await expect(page.getByText("Not yet checked")).toHaveCount(0);
});

test("a validated anomaly shows a grounded report with working citations", async ({ page }) => {
  await loginAs(page, "analyst", "analyst123");
  await page.getByText("Revenue", { exact: true }).click();
  await expect(page.getByText("Anomaly history")).toBeVisible();

  await page.locator(".anomaly-row").first().click();
  await expect(page.getByText("PROBLEM")).toBeVisible();
  // Exact match: the page also has a "Root Cause Evidence Chain" heading, which a loose
  // case-insensitive substring match on "CAUSE" would collide with.
  await expect(page.locator(".report-label", { hasText: "Cause" })).toBeVisible();

  const citation = page.locator(".citation-chip").first();
  await expect(citation).toBeVisible();
  const href = await citation.getAttribute("href");
  expect(href).toMatch(/^#evidence-\d+$/);

  await citation.click();
  const targetId = href!.slice(1);
  await expect(page.locator(`#${targetId}`)).toBeVisible();
});

test("a genuinely ambiguous case shows multiple ranked hypotheses, never a single fabricated cause", async ({ page }) => {
  await loginAs(page, "analyst", "analyst123");
  await page.getByText("Customer Satisfaction (CSAT)").click();
  await page.locator(".anomaly-row").first().click();

  await expect(page.getByRole("heading", { name: "Evidence Gap" })).toBeVisible();
  const hypotheses = page.locator(".hypothesis-card");
  expect(await hypotheses.count()).toBeGreaterThanOrEqual(2);

  const gapCount = await page.locator(".disambiguation-gap").count();
  expect(gapCount).toBe(await hypotheses.count());
});

test("reports page filters by department", async ({ page }) => {
  await loginAs(page, "admin", "admin123");
  await page.goto("/reports");
  await expect(page.getByRole("heading", { name: "Reports" })).toBeVisible();
  await page.getByRole("button", { name: "Sales" }).click();
  await expect(page.locator(".report-row-metric", { hasText: "Revenue" })).toBeVisible();
});

test("admin page shows the suppressed-log audit trail and playbook library", async ({ page }) => {
  await loginAs(page, "admin", "admin123");
  await page.goto("/admin");
  await expect(page.getByText("Suppressed log")).toBeVisible();
  await expect(page.locator("table tbody tr").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Playbook library" })).toBeVisible();
  await expect(page.locator(".playbook-card").first()).toBeVisible();
});

test("analyst cannot see the Admin nav link or reach /admin directly", async ({ page }) => {
  await loginAs(page, "analyst", "analyst123");
  await expect(page.getByRole("link", { name: "Admin" })).toHaveCount(0);

  await page.goto("/admin");
  await expect(page).toHaveURL("http://localhost:5173/");
});

test("executive can view a KPI but has no Run detection action", async ({ page }) => {
  await loginAs(page, "exec", "exec123");
  await expect(page.getByRole("button", { name: "Run detection" })).toHaveCount(0);

  await page.getByText("Revenue", { exact: true }).click();
  await expect(page.getByText("Anomaly history")).toBeVisible();
  await expect(page.getByRole("button", { name: "Run detection on latest window" })).toHaveCount(0);
});

test("sign out clears the session and returns to login", async ({ page }) => {
  await loginAs(page, "admin", "admin123");
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);

  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
});
