import { defineConfig, devices } from "@playwright/test";

/**
 * V1 acceptance e2e: Chromium against the Vite dev server with the analytical
 * API intercepted by deterministic contract-shaped fixtures (no PostgreSQL, no
 * dataset download). Docker Compose remains the full-stack reproduction path.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  timeout: 60_000,
  expect: { timeout: 20_000 },
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "pnpm run dev --host 127.0.0.1 --port 4173 --strictPort",
    url: "http://127.0.0.1:4173/catalog",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
