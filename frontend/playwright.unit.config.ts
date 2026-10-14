import { defineConfig } from "@playwright/test";

// Fetch is controlled by these tests; no browser, API server or database is started.
export default defineConfig({testDir: "./tests/unit", outputDir: "./test-results/unit", workers: 1});
