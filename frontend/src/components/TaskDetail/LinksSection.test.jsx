import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { LinksSection } from './LinksSection';
import { api } from '../../api';

vi.mock('../../api', () => ({
    api: {
        listTaskLinks: vi.fn(),
        listTasks: vi.fn(),
        listMilestones: vi.fn(),
        updateTask: vi.fn(),
        addTaskLink: vi.fn(),
        removeTaskLink: vi.fn(),
    },
}));

const TASK = {
    id: 't1', key: 'AP-1', title: 'Parent work', project_id: 'p1',
    status: 'in_progress', parent_id: null, milestone_id: null,
};

function renderSection(task = TASK, onChanged = vi.fn(), isEditing = false, onOpenTask) {
    return render(
        <MemoryRouter>
            <LinksSection task={task} onChanged={onChanged} isEditing={isEditing}
                          onOpenTask={onOpenTask} />
        </MemoryRouter>
    );
}

beforeEach(() => {
    vi.clearAllMocks();
    api.listTaskLinks.mockResolvedValue([
        { id: 'l1', type: 'depends_on', task: { id: 't3', key: 'AP-3', title: 'Do first', status: 'todo' } },
        { id: 'parent:t2', type: 'parent_of', task: { id: 't2', key: 'AP-2', title: 'Child work', status: 'done' } },
    ]);
    api.listTasks.mockResolvedValue([
        { id: 't1', key: 'AP-1', title: 'Parent work', status: 'in_progress' },
        { id: 't3', key: 'AP-3', title: 'Do first', status: 'todo' },
        { id: 't4', key: 'AP-4', title: 'Later work', status: 'backlog' },
    ]);
    api.listMilestones.mockResolvedValue([
        { id: 'm1', title: 'Public beta', due_date: '2026-09-01T00:00:00+00:00' },
    ]);
    api.updateTask.mockResolvedValue({});
    api.addTaskLink.mockResolvedValue({ id: 'l9' });
    api.removeTaskLink.mockResolvedValue({ ok: true });
});

describe('LinksSection', () => {
    it('groups links under their plain-language label', async () => {
        renderSection();
        expect(await screen.findByText('Do first')).toBeInTheDocument();
        expect(screen.getByText('Waits on')).toBeInTheDocument();
        expect(screen.getByText('Subtasks')).toBeInTheDocument();
        expect(screen.getByText('Child work')).toBeInTheDocument();
    });

    it('adds a link without edit mode', async () => {
        renderSection();
        await screen.findByText('Do first');

        fireEvent.click(screen.getByTitle('Add a link'));
        fireEvent.change(screen.getByLabelText('Link type'), { target: { value: 'blocks' } });
        fireEvent.change(screen.getByLabelText('Task to link'), { target: { value: 't4' } });
        fireEvent.click(screen.getByText('Add link'));

        await waitFor(() => expect(api.addTaskLink).toHaveBeenCalledWith('t1', 't4', 'blocks'));
    });

    it('only offers removal in edit mode', async () => {
        const { unmount } = renderSection();
        await screen.findByText('Do first');
        expect(screen.queryByTitle('Remove this link')).not.toBeInTheDocument();
        unmount();

        renderSection(TASK, vi.fn(), true);
        const chip = (await screen.findByText('Do first')).closest('div');
        fireEvent.click(within(chip).getByTitle('Remove this link'));
        await waitFor(() => expect(api.removeTaskLink).toHaveBeenCalledWith('t1', 'l1'));
    });

    it('opens a linked task through the supplied side-panel callback', async () => {
        const onOpenTask = vi.fn();
        renderSection(TASK, vi.fn(), false, onOpenTask);

        fireEvent.click(await screen.findByRole('button', { name: 'AP-3' }));
        expect(onOpenTask).toHaveBeenCalledWith('t3');
    });

    it('surfaces a rejected link instead of failing silently', async () => {
        api.addTaskLink.mockRejectedValueOnce(new Error('that link would create a cycle'));
        renderSection();
        await screen.findByText('Do first');

        fireEvent.click(screen.getByTitle('Add a link'));
        fireEvent.change(screen.getByLabelText('Task to link'), { target: { value: 't4' } });
        fireEvent.click(screen.getByText('Add link'));

        expect(await screen.findByText(/would create a cycle/)).toBeInTheDocument();
    });

    it('links the task to a milestone', async () => {
        renderSection(TASK, vi.fn(), true);
        await screen.findByText('Counts towards');
        const picker = screen.getAllByRole('combobox').find(
            el => el.textContent.includes('No milestone'));
        fireEvent.change(picker, { target: { value: 'm1' } });
        await waitFor(() => expect(api.updateTask).toHaveBeenCalledWith('t1', { milestone_id: 'm1' }));
    });
});
