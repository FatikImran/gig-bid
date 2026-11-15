import { randomBytes } from "node:crypto";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";

if (!process.env.GIGBID_OAUTH_ENCRYPTION_KEY) {
  throw new Error("Run the Upwork test in the PowerShell session that set the OAuth encryption key.");
}

const apiURL = "http://127.0.0.1:8011";
const webURL = "http://127.0.0.1:5174";
const repoRoot = fileURLToPath(new URL("../..", import.meta.url));
const apiToken = process.env.GIGBID_UPWORK_TEST_TOKEN ??= randomBytes(32).toString("hex");

export default defineConfig({
  testDir: "./tests/live",
  workers: 1,
  reporter: "list",
  timeout: 90_000,
  expect: { timeout: 35_000 },
  use: { ...devices["Desktop Chrome"], baseURL: webURL },
  webServer: [
    {
      command: "python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8011",
      cwd: repoRoot,
      url: `${apiURL}/health`,
      reuseExistingServer: false,
      env: {
        GIGBID_API_TOKEN: apiToken,
        GIGBID_CORS_ORIGINS: webURL,
        GIGBID_MARKETPLACE_MODE: "upwork",
      },
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5174 --strictPort",
      url: webURL,
      reuseExistingServer: false,
      env: { VITE_API_URL: apiURL, GIGBID_OAUTH_ENCRYPTION_KEY: "" },
    },
  ],
});
