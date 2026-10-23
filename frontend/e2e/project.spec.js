import { test, expect } from '@playwright/test';
import { createProject, uniqueName } from './helpers.js';

test('create a project and see it on the board and the home page', async ({ page }) => {
    const name = uniqueName('Project');
    await createProject(page, name);
    for (const column of ['Backlog', 'To Do', 'In Progress', 'Review', 'Done']) {
        await expect(page.getByText(column, { exact: true }).first()).toBeVisible();
    }

    await page.goto('/studio');
    await expect(page.getByRole('button', { name: `Open ${name}` })).toBeVisible();
});
