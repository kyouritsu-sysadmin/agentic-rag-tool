import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir:"./tests", outputDir:"./test-results", workers:1, use:{baseURL:"http://127.0.0.1:3018", headless:true},
  webServer:[
    {command:"../.venv/bin/uvicorn tests.e2e.browser_server:app --app-dir ../backend --host 127.0.0.1 --port 8018", url:"http://127.0.0.1:8018/health/live", timeout:30_000},
    {command:"npm run start", env:{HOSTNAME:"127.0.0.1", PORT:"3018"}, url:"http://127.0.0.1:3018", timeout:30_000},
  ],
});
