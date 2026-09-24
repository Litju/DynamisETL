import { defineConfig, devices } from "@playwright/test";

/**
 * RES-112 real-data acceptance: Chromium against the running workbench and the
 * real local analytical API. Nothing is intercepted or mocked; a missing local
 * artifact fails the run instead of silently rendering an empty route.
 *
 * Prepare the data first (`uv run dynamis-demo-prepare`), start the API
 * (`uv run dynamis-serve`) and the workbench, then run
 * `pnpm --filter @dynamis/web run test:e2e:real`. Point the suite at another
 * server with DYNAMIS_REAL_BASE_URL (default http://127.0.0.1:5173).
 */
const baseURL = process.env.DYNAMIS_REAL_BASE_URL ?? "http://127.0.0.1:5173";

export default defineConfig({
  testDir: "./e2e-real",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  timeout: 180_000,
  expect: { timeout: 45_000 },
  use: {
    baseURL,
    viewport: { width: 1440, height: 900 },
    actionTimeout: 10_000,
    navigationTimeout: 45_000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "real-chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
});
