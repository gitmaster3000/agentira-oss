import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { RelationsSection } from './RelationsSection';
import { api } from '../../api';

vi.mock('../../api', () => ({
    api: {
        listSubtasks: vi.fn(),
        listTasks: vi.fn(),
        listMilestones: vi.fn(),
        updateTask: vi.fn(),
        addDependency: vi.fn(),
        listDependencies: vi.fn(),
        removeDependency: vi.fn(),
    },
}));

const TASK = {
    id: 't1', key: 'AP-1', title: 'Parent work', project_id: 'p1',
    status: 'in_progress', parent_id: null, milestone_id: null,
    blocked_by: [{ id: 't3', key: 'AP-3', title: 'Do first', status: 'todo' }],
    blocks: [],
};

function renderSection(task = TASK, onChanged = vi.fn()) {
    return render(
        <MemoryRouter>
            <RelationsSection task={task} onChanged={onChanged} />
        </MemoryRouter>
    );
}

beforeEach(() => {
    vi.clearAllMocks();
    api.listSubtasks.mockResolvedValue([
        { id: 't2', key: 'AP-2', title: 'Child work', status: 'done' },
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
    api.addDependency.mockResolvedValue({ id: 'd9' });
});

describe('RelationsSection', () => {
    it('lists subtasks with a done count', async () => {
        renderSection();
        expect(await screen.findByText('Child work')).toBeInTheDocument();
        expect(screen.getByText(/Subtasks \(1\/1\)/)).toBeInTheDocument();
    });

    it('shows what the task waits on', async () => {
        renderSection();
        expect(await screen.findByText('Do first')).toBeInTheDocument();
        expect(screen.getByText('Waits on')).toBeInTheDocument();
    });

    it('says so plainly when nothing is waiting on the task', async () => {
        renderSection();
        expect(await screen.findByText('Nothing is waiting on this.')).toBeInTheDocument();
    });

    it('adds a dependency in the task → blocker direction', async () => {
        renderSection();
        await screen.findByText('Do first');

        fireEvent.click(screen.getByTitle('Add something this task waits on'));
        // The picker is the newly rendered combobox holding the placeholder.
        const picker = screen.getAllByRole('combobox').find(
            el => el.textContent.includes("This task can't start until"));
        fireEvent.change(picker, { target: { value: 't4' } });
        fireEvent.click(screen.getByText('Add'));

        await waitFor(() => expect(api.addDependency).toHaveBeenCalledWith('p1', 't1', 't4'));
    });

    it('links the task to a milestone', async () => {
        renderSection();
        await screen.findByText('Counts towards');
        const picker = screen.getAllByRole('combobox').find(
            el => el.textContent.includes('No milestone'));
        fireEvent.change(picker, { target: { value: 'm1' } });
        await waitFor(() => expect(api.updateTask).toHaveBeenCalledWith(
            't1', { milestone_id: 'm1' }));
    });

    it('surfaces a rejected graph change instead of failing silently', async () => {
        api.updateTask.mockRejectedValueOnce(
            new Error('that parent would create a cycle in the task tree'));
        renderSection();
        await screen.findByText('Child work');

        const parentPicker = screen.getAllByRole('combobox').find(
            el => el.textContent.includes('Not part of a bigger task'));
        fireEvent.change(parentPicker, { target: { value: 't4' } });

        expect(await screen.findByText(/would create a cycle/)).toBeInTheDocument();
    });
});
