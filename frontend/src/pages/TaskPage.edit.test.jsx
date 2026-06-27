import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { TaskPage } from './TaskPage';
import { api } from '../api';

vi.mock('../api', () => ({
    api: {
        getTask: vi.fn(),
        getActivity: vi.fn(() => Promise.resolve([])),
        getProjectMembers: vi.fn(() => Promise.resolve([])),
        listTaskCommits: vi.fn(() => Promise.resolve([])),
        listProjectRepos: vi.fn(() => Promise.resolve([])),
        listAttachments: vi.fn(() => Promise.resolve([])),
        addComment: vi.fn(() => Promise.resolve({})),
        updateTask: vi.fn(() => Promise.resolve({})),
        forge: {
            listTaskRuns: vi.fn(() => Promise.resolve([])),
            listAgents: vi.fn(() => Promise.resolve([])),
            prepareTaskRun: vi.fn(() => Promise.resolve({ id: 'run-99' })),
        },
    },
}));

vi.mock('../context/AuthContext', () => ({
    useAuth: () => ({ user: { display_name: 'Tester' } }),
}));

function baseTask(overrides = {}) {
    return {
        id: 'T1',
        key: 'AP-1',
        title: 'My task',
        description: 'the original description',
        status: 'todo',
        priority: 'medium',
        assignee: '',
        dod_items: [],
        tags: [],
        branch: '',
        pr_url: '',
        repos: [],
        project_id: 'P1',
        created_at: '2026-06-01T00:00:00Z',
        updated_at: '2026-06-01T00:00:00Z',
        ...overrides,
    };
}

function renderTaskPage() {
    return render(
        <MemoryRouter initialEntries={['/studio/tasks/T1']}>
            <Routes>
                <Route path="/studio/tasks/:taskId" element={<TaskPage />} />
            </Routes>
        </MemoryRouter>,
    );
}

describe('TaskPage — edit mode (AP-353)', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.getTask.mockResolvedValue(baseTask());
        api.forge.listTaskRuns.mockResolvedValue([]);
        api.forge.listAgents.mockResolvedValue([
            { id: 'a1', name: 'Implementer', runtime_id: 'rt1', model: 'opus', status: 'online' },
        ]);
    });

    it('exposes an Edit affordance on the task page', async () => {
        renderTaskPage();
        await screen.findByText('My task');
        expect(screen.getByTitle('Edit task')).toBeInTheDocument();
    });

    it('reveals editable Title and Description prefilled with the task', async () => {
        renderTaskPage();
        await screen.findByText('My task');
        fireEvent.click(screen.getByTitle('Edit task'));

        expect(screen.getByLabelText('Title').value).toBe('My task');
        expect(screen.getByLabelText('Description').value).toBe('the original description');
    });

    it('saves edited Title and Description via updateTask', async () => {
        renderTaskPage();
        await screen.findByText('My task');
        fireEvent.click(screen.getByTitle('Edit task'));

        fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Renamed task' } });
        fireEvent.change(screen.getByLabelText('Description'), { target: { value: 'new body' } });
        fireEvent.click(screen.getByRole('button', { name: /save/i }));

        await waitFor(() => expect(api.updateTask).toHaveBeenCalledWith(
            'T1',
            expect.objectContaining({ title: 'Renamed task', description: 'new body' }),
        ));
    });

    it('Cancel exits edit mode without saving', async () => {
        renderTaskPage();
        await screen.findByText('My task');
        fireEvent.click(screen.getByTitle('Edit task'));

        fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'discard me' } });
        fireEvent.click(screen.getByRole('button', { name: /cancel/i }));

        expect(api.updateTask).not.toHaveBeenCalled();
        expect(screen.queryByLabelText('Title')).not.toBeInTheDocument();
        expect(screen.getByTitle('Edit task')).toBeInTheDocument();
    });

    it('can start an agent run from the Agent tab (regression guard)', async () => {
        renderTaskPage();
        await screen.findByText('My task');

        fireEvent.click(screen.getByRole('button', { name: /agent/i }));
        fireEvent.click(await screen.findByRole('button', { name: /run with agent/i }));

        fireEvent.click(await screen.findByText('Implementer'));

        await waitFor(() =>
            expect(api.forge.prepareTaskRun).toHaveBeenCalledWith('T1', 'a1'));
    });
});
