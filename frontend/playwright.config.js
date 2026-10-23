import { defineConfig } from '@playwright/test';

// Browser tests run against an already-running stack (see
// docs-oss/docs/contributing/testing.md): E2E_BASE_URL is the web app.
const baseURL = process.env.E2E_BASE_URL || 'http://localhost:3111';

export default defineConfig({
    testDir: './e2e',
    testMatch: '**/*.spec.js',
    globalSetup: './e2e/global-setup.js',
    fullyParallel: true,
    forbidOnly: !!process.env.CI,
    retries: process.env.CI ? 1 : 0,
    workers: process.env.CI ? 2 : undefined,
    expect: { timeout: 10_000 },
    reporter: [['list'], ['html', { open: 'never' }]],
    use: {
        baseURL,
        storageState: 'e2e/.auth/user.json',
        trace: 'on-first-retry',
    },
    projects: [
        { name: 'desktop', testIgnore: '**/mobile.spec.js', use: { viewport: { width: 1440, height: 900 } } },
        { name: 'mobile', use: { viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true } },
    ],
});
