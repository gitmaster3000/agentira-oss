import { test, expect } from '@playwright/test';
import { createProject, uniqueName } from './helpers.js';

test('epics list opens and shows a new epic', async ({ page }) => {
    const { id } = await createProject(page);
    await page.goto(`/studio/project/${id}/epics`);
    await expect(page.getByRole('heading', { name: 'Epics', level: 3 })).toBeVisible();
    await expect(page.getByText('No epics yet')).toBeVisible();

    const title = uniqueName('Epic');
    await page.getByRole('button', { name: 'New epic' }).click();
    await page.getByPlaceholder('What are we aiming for?').fill(title);
    await page.getByRole('button', { name: 'Create Epic' }).click();
    await expect(page.getByRole('heading', { name: title, level: 1 })).toBeVisible();

    await page.goto(`/studio/project/${id}/epics`);
    await expect(page.getByRole('button', { name: new RegExp(title) })).toBeVisible();
});

test('roadmap view renders with the project tasks', async ({ page }) => {
    const { id, name } = await createProject(page);
    await page.goto(`/studio/project/${id}/roadmap`);
    await expect(page.getByRole('heading', { name: `Roadmap — ${name}` })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Schedule', level: 3 })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Timeline' })).toBeVisible();
});

test('the Build area renders the agents page', async ({ page }) => {
    await page.goto('/studio');
    await page.getByRole('button', { name: 'Build' }).click();
    await expect(page).toHaveURL(/\/forge/);
    await page.goto('/forge/agents');
    await expect(page.getByRole('heading', { name: 'Agents', level: 1 })).toBeVisible();
    await expect(page.getByRole('button', { name: 'New Agent' })).toBeVisible();
});

test('the notifications bell opens and closes', async ({ page }) => {
    await page.goto('/studio');
    const bell = page.getByRole('button', { name: 'Notifications' });
    await bell.click();
    await expect(bell).toHaveAttribute('aria-expanded', 'true');
    await expect(page.getByText('Open Inbox')).toBeVisible();
    await bell.click();
    await expect(page.getByText('Open Inbox')).toBeHidden();
});

test('the theme toggle switches between dark and light and remembers it', async ({ page }) => {
    await page.goto('/studio');
    const html = page.locator('html');
    await page.getByRole('button', { name: /^Switch to (light|dark) mode$/ }).click();
    const first = await html.getAttribute('data-theme');
    await page.getByRole('button', { name: /^Switch to (light|dark) mode$/ }).click();
    const second = await html.getAttribute('data-theme');
    expect(new Set([first, second])).toEqual(new Set(['light', 'dark']));

    await page.reload();
    await expect(html).toHaveAttribute('data-theme', second);
});
