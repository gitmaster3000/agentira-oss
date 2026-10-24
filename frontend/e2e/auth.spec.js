import { test, expect } from '@playwright/test';
import { E2E_USER, E2E_PASSWORD } from './credentials.js';

test.describe('signed out', () => {
    test.use({ storageState: { cookies: [], origins: [] } });

    test('wrong password is rejected', async ({ page }) => {
        await page.goto('/login');
        await page.getByLabel('Username').fill(E2E_USER);
        await page.getByLabel('Password').fill('not-the-password');
        await page.getByRole('button', { name: 'Sign In' }).click();
        await expect(page.getByText('Invalid username or password')).toBeVisible();
        await expect(page).toHaveURL(/\/login/);
    });

    test('signing in lands on the workspace', async ({ page }) => {
        await page.goto('/login');
        await page.getByLabel('Username').fill(E2E_USER);
        await page.getByLabel('Password').fill(E2E_PASSWORD);
        await page.getByRole('button', { name: 'Sign In' }).click();
        await expect(page).toHaveURL(/\/studio$/);
        await expect(page.getByRole('heading', { name: /^Good (morning|afternoon|evening), / })).toBeVisible();
    });

    test('a private page sends you to sign in', async ({ page }) => {
        await page.goto('/studio');
        await expect(page).toHaveURL(/\/(login|welcome)$/);
        await expect(page.getByRole('button', { name: 'New project' })).toHaveCount(0);
    });
});

test('a saved session opens the workspace directly', async ({ page }) => {
    await page.goto('/studio');
    await expect(page.getByRole('button', { name: 'New project' })).toBeVisible();
});
