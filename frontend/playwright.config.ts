import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 120_000,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: "https://localhost:3000",
    ignoreHTTPSErrors: true,
    video: "retain-on-failure",
    screenshot: "only-on-failure",
    // Bypass the system proxy so localhost traffic reaches the dev server directly.
    // --ignore-certificate-errors is required so that the native WebSocket API
    // (used by the Centrifuge client) can connect to wss://localhost:22332 which
    // serves a self-signed certificate.  ignoreHTTPSErrors only suppresses cert
    // errors for HTTP requests intercepted by the CDP Network domain; it does NOT
    // cover WebSocket connections opened by in-page JavaScript.
    launchOptions: {
      args: ["--no-proxy-server", "--ignore-certificate-errors"],
    },
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  // Do not spin up dev server automatically — run manually before the test.
  webServer: undefined,
  outputDir: "tests/results",
});
