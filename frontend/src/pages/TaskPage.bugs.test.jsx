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
        getEpics: vi.fn(() => Promise.resolve([])),
        listTaskCommits: vi.fn(() => Promise.resolve([])),
        listProjectRepos: vi.fn(() => Promise.resolve([])),
        listAttachments: vi.fn(() => Promise.resolve([])),
        listSubtasks: vi.fn(() => Promise.resolve([])),
        listTasks: vi.fn(() => Promise.resolve([])),
        listMilestones: vi.fn(() => Promise.resolve([])),
        listTaskLinks: vi.fn(() => Promise.resolve([])),
        addComment: vi.fn(() => Promise.resolve({})),
        updateTask: vi.fn(() => Promise.resolve({})),
        moveTask: vi.fn(() => Promise.resolve({})),
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

// The side panel's "Open full" link navigates by task KEY, so that's what the
// real URL carries — not the task's primary id.
function renderTaskPageByKey() {
    return render(
        <MemoryRouter initialEntries={['/studio/tasks/AP-1']}>
            <Routes>
                <Route path="/studio/tasks/:taskId" element={<TaskPage />} />
            </Routes>
        </MemoryRouter>,
    );
}

describe('TaskPage — full detail view bugs', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.getTask.mockResolvedValue(baseTask());
        api.forge.listTaskRuns.mockResolvedValue([]);
        api.forge.listAgents.mockResolvedValue([
            { id: 'a1', name: 'Implementer', runtime_id: 'rt1', model: 'opus', status: 'online' },
        ]);
    });

    it('starts a run with the task id even when the URL carries the task key', async () => {
        renderTaskPageByKey();
        await screen.findByText('My task');

        fireEvent.click(screen.getByRole('button', { name: /^run$/i }));
        fireEvent.click(await screen.findByRole('button', { name: /run with agent/i }));
        fireEvent.click(await screen.findByText('Implementer'));

        await waitFor(() =>
            expect(api.forge.prepareTaskRun).toHaveBeenCalledWith('T1', 'a1'));
    });

    it('polls task runs by task id, not by the key in the URL', async () => {
        renderTaskPageByKey();
        await screen.findByText('My task');
        await waitFor(() => expect(api.forge.listTaskRuns).toHaveBeenCalledWith('T1'));
        expect(api.forge.listTaskRuns).not.toHaveBeenCalledWith('AP-1');
    });

    it('renders no in-page breadcrumb (the app topbar already has one)', async () => {
        renderTaskPageByKey();
        await screen.findByText('My task');
        expect(screen.queryByRole('navigation')).toBeNull();
    });

    it('opens the create-task modal when the topbar "New task" event fires', async () => {
        renderTaskPageByKey();
        await screen.findByText('My task');

        fireEvent(window, new CustomEvent('open-create-task'));

        expect(await screen.findByRole('heading', { name: 'New Task' })).toBeInTheDocument();
    });
});
