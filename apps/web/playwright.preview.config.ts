import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.DYNAMIS_REAL_BASE_URL;
if (!baseURL || new URL(baseURL).protocol !== "https:") {
  throw new Error("DYNAMIS_REAL_BASE_URL must be the HTTPS Vercel Preview URL");
}

export default defineConfig({
  testDir: "./e2e-deploy",
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
  projects: [{ name: "vercel-preview", use: { ...devices["Desktop Chrome"] } }],
});
