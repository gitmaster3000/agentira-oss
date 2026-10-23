import { chromium } from '@playwright/test';
import { E2E_USER, E2E_PASSWORD } from './credentials.js';

// Sign in once through the real login page and save the session for every spec.
export default async function globalSetup(config) {
    const { baseURL } = config.projects[0].use;
    const browser = await chromium.launch();
    const page = await browser.newPage({ baseURL });
    await page.goto('/login');
    await page.getByLabel('Username').fill(E2E_USER);
    await page.getByLabel('Password').fill(E2E_PASSWORD);
    await page.getByRole('button', { name: 'Sign In' }).click();
    await page.waitForURL('**/studio');
    await page.context().storageState({ path: 'e2e/.auth/user.json' });
    await browser.close();
}
