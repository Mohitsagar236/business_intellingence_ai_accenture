import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: false,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: "http://localhost:5173",
    screenshot: "only-on-failure",
  },
  // Assumes the backend (127.0.0.1:8000) and `npm run dev` are already running —
  // this suite drives the app, it doesn't stand up the stack. See README "Testing".
  //
  // golden-path.spec.ts asserts against the known synthetic scenarios (validated/ambiguous/
  // suppressed) — run `python backend/scripts/seed_test_fixture.py` first to seed them.
  // data-ingestion.spec.ts creates and cleans up its own metric via the real upload path and
  // has no seed dependency.
  //
  // Both spec files drive the SAME live backend and SQLite file — there's no per-worker
  // backend/DB isolation in this harness. The dashboard's KPI count in golden-path.spec.ts
  // reads the global metrics table, and data-ingestion.spec.ts briefly adds/removes real rows
  // in that same table. Run in different workers, those two can interleave: the dashboard read
  // can land while data-ingestion's temporary metric still exists, throwing off the exact-count
  // assertion. `dependencies` forces data-ingestion.spec.ts to finish (and clean up) before
  // golden-path.spec.ts starts, without capping worker parallelism for tests in general.
  projects: [
    { name: "data-ingestion", testMatch: "data-ingestion.spec.ts" },
    { name: "golden-path", testMatch: "golden-path.spec.ts", dependencies: ["data-ingestion"] },
  ],
});
