import { expect } from '@playwright/test';

// Unique per call so specs never collide on shared data.
export const uniqueName = (prefix) =>
    `${prefix} ${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

// Create a project through the wizard and land on its board. Returns its id.
export async function createProject(page, name = uniqueName('E2E project')) {
    await page.goto('/studio');
    await page.getByRole('button', { name: 'New project' }).click();
    await page.getByPlaceholder('e.g. LeadCore').fill(name);
    for (let step = 0; step < 3; step++) await page.getByRole('button', { name: 'Next', exact: true }).click();
    await page.getByRole('button', { name: 'Create project' }).click();
    await expect(page).toHaveURL(/\/studio\/project\/[^/]+\/board/);
    await expect(page.getByRole('heading', { name, level: 2 })).toBeVisible();
    return { name, id: page.url().match(/project\/([^/]+)\//)[1] };
}

// Create a task from the board's New task dialog. Stays on the board.
export async function createTask(page, title = uniqueName('E2E task'), description = '') {
    await page.getByRole('button', { name: 'New task' }).click();
    await page.getByRole('textbox', { name: 'Title' }).fill(title);
    if (description) await page.getByRole('textbox', { name: 'Description' }).fill(description);
    await page.getByRole('button', { name: 'Create', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'New task' })).toBeHidden();
    await expect(page.getByText(title)).toBeVisible();
    return title;
}
