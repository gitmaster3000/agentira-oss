import { test, expect } from '@playwright/test';
import { createProject, createTask, uniqueName } from './helpers.js';

test('create, open, edit, comment on and move a task', async ({ page }) => {
    const { id } = await createProject(page);
    const title = await createTask(page, uniqueName('Task'), 'first description');

    // Open it from the board.
    await page.getByText(title).click();
    await expect(page).toHaveURL(/\/studio\/tasks\/[A-Z0-9]+-\d+/);
    await expect(page.getByRole('heading', { name: title, level: 1 })).toBeVisible();
    await expect(page.getByText('first description')).toBeVisible();

    // Edit title and description.
    const newTitle = `${title} edited`;
    await page.getByRole('button', { name: 'Edit', exact: true }).click();
    await page.getByRole('textbox', { name: 'Title' }).fill(newTitle);
    await page.getByRole('textbox', { name: 'Description' }).fill('second description');
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByRole('heading', { name: newTitle, level: 1 })).toBeVisible();
    await expect(page.getByText('second description')).toBeVisible();

    // Comment.
    await page.getByRole('textbox', { name: /Add a comment/ }).fill('looks good to me');
    await page.getByRole('button', { name: 'Add Comment' }).click();
    await expect(page.getByText('looks good to me')).toBeVisible();

    // Move to another column, then check the board agrees.
    await page.getByRole('combobox', { name: 'Status' }).selectOption({ label: 'In Progress' });
    await expect(page.getByRole('combobox', { name: 'Status' })).toHaveValue('in_progress');
    await page.reload();
    await expect(page.getByRole('combobox', { name: 'Status' })).toHaveValue('in_progress');
    await page.goto(`/studio/project/${id}/board`);
    await expect(page.getByText(newTitle)).toBeVisible();
});
