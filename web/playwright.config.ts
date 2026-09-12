import { defineConfig } from "@playwright/test";

const SERVER_PORT = 8123;
const WEB_PORT = 5273;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "retain-on-failure",
  },
  webServer: [
    {
      // A scripted model, and its own database file so a run cannot inherit
      // tasks from the last one.
      command: `rm -f e2e.db && AGENT_MODEL=test DB_PATH=e2e.db uv run uvicorn tests.e2e_app:app --port ${SERVER_PORT}`,
      cwd: "../server",
      url: `http://localhost:${SERVER_PORT}/conversations`,
      reuseExistingServer: false,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: `pnpm vite --port ${WEB_PORT} --strictPort`,
      url: `http://localhost:${WEB_PORT}`,
      reuseExistingServer: false,
      env: { VITE_SERVER_URL: `localhost:${SERVER_PORT}` },
    },
  ],
});
