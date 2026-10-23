import { test, expect } from '@playwright/test';
import { createProject, createTask } from './helpers.js';

// Runs in the `mobile` project only (see playwright.config.js).
const noSidewaysScroll = (page) =>
    page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

test('the board and the task page do not scroll sideways at 375px', async ({ page }) => {
    await createProject(page);
    const title = await createTask(page);
    expect(await noSidewaysScroll(page)).toBeLessThanOrEqual(0);

    await page.getByText(title).click();
    await expect(page.getByRole('heading', { name: title, level: 1 })).toBeVisible();
    expect(await noSidewaysScroll(page)).toBeLessThanOrEqual(0);
});
