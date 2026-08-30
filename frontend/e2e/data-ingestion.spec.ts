import { test, expect } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * Exercises the real-data path this app now runs on: create a metric, upload a CSV through
 * the browser (not the API directly), confirm it lands in the chart, run detection, then clean
 * up. Independent of the synthetic test-fixture — this is what a first-time admin actually does.
 */

const fixtureCsv = path.join(__dirname, "fixtures", "sample_observations.csv");

test("admin can create a metric, upload real observations, and see them charted", async ({ page }) => {
  const key = `e2e_metric_${Date.now()}`;

  await page.goto("/login");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("admin123");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForSelector("text=Dashboard");

  await page.locator("nav.topnav").getByRole("link", { name: "Data" }).click();
  await expect(page.getByRole("heading", { name: "Create a metric" })).toBeVisible();

  await page.locator('input[placeholder="revenue"]').fill(key);
  await page.locator('input[placeholder="Revenue"]').fill("E2E Test Metric");
  await page.locator('input[placeholder="Sales"]').fill("Sales");
  await page.locator('input[placeholder="USD"]').fill("USD");
  await page.locator('input[placeholder="region, product"]').fill("region");
  await page.getByRole("button", { name: "Create metric" }).click();
  await expect(page.getByText('Created "E2E Test Metric"')).toBeVisible();

  const row = page.locator(".metric-row", { hasText: "E2E Test Metric" });
  await row.locator('input[type="file"]').setInputFiles(fixtureCsv);
  await expect(row.getByText(/Inserted 14 row/)).toBeVisible();
  await expect(row.getByText(/14 observations/)).toBeVisible();

  await row.getByRole("link", { name: "E2E Test Metric" }).click();
  await expect(page.getByText("Anomaly history")).toBeVisible();
  await expect(page.locator(".ts-chart")).toBeVisible();
  // 14 days == exactly 2x a 7-day seasonality period, so this sits right at the boundary —
  // it should NOT show the insufficient-history notice.
  await expect(page.getByText(/trend\/seasonal decomposition needs/)).toHaveCount(0);

  await page.getByRole("button", { name: "Run detection on latest window" }).click();
  await expect(page.locator(".run-feedback-ok")).toContainText("Ran just now");

  // Clean up: delete the metric via the UI (also exercises the delete path).
  await page.locator("nav.topnav").getByRole("link", { name: "Data" }).click();
  page.once("dialog", (dialog) => dialog.accept());
  await page.locator(".metric-row", { hasText: "E2E Test Metric" }).getByRole("button", { name: "Delete" }).click();
  await expect(page.locator(".metric-row", { hasText: "E2E Test Metric" })).toHaveCount(0);
});

test("uploading a CSV with a missing required column shows a clear error, not a silent failure", async ({ page }) => {
  const key = `e2e_bad_${Date.now()}`;

  await page.goto("/login");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("admin123");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForSelector("text=Dashboard");

  await page.locator("nav.topnav").getByRole("link", { name: "Data" }).click();
  await page.locator('input[placeholder="revenue"]').fill(key);
  await page.locator('input[placeholder="Revenue"]').fill("Bad Upload Test");
  await page.locator('input[placeholder="Sales"]').fill("Sales");
  await page.locator('input[placeholder="USD"]').fill("USD");
  await page.locator('input[placeholder="region, product"]').fill("region");
  await page.getByRole("button", { name: "Create metric" }).click();
  await expect(page.getByText('Created "Bad Upload Test"')).toBeVisible();

  const row = page.locator(".metric-row", { hasText: "Bad Upload Test" });
  // Missing the required 'region' dimension column entirely.
  const buffer = Buffer.from("date,value\n2026-05-01,100\n");
  await row.locator('input[type="file"]').setInputFiles({ name: "bad.csv", mimeType: "text/csv", buffer });
  await expect(row.locator(".run-feedback-error")).toContainText("region");

  page.once("dialog", (dialog) => dialog.accept());
  await row.getByRole("button", { name: "Delete" }).click();
});
