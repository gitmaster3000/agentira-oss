import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
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
        listSubtasks: vi.fn(() => Promise.resolve([])),
        listTasks: vi.fn(() => Promise.resolve([])),
        listMilestones: vi.fn(() => Promise.resolve([])),
        listDependencies: vi.fn(() => Promise.resolve([])),
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
        tags: ['alpha'],
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

describe('TaskPage — detail view (AP-353)', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.getTask.mockResolvedValue(baseTask());
        api.forge.listTaskRuns.mockResolvedValue([]);
        api.forge.listAgents.mockResolvedValue([
            { id: 'a1', name: 'Implementer', runtime_id: 'rt1', model: 'opus', status: 'online' },
        ]);
    });

    it('has no separate Agent tab', async () => {
        renderTaskPage();
        await screen.findByText('My task');
        expect(screen.queryByRole('button', { name: /^agent$/i })).toBeNull();
    });

    it('does not show a run-status pill in the header for a failed run', async () => {
        api.forge.listTaskRuns.mockResolvedValue([
            { id: 'r1', status: 'failed', created_at: '2026-06-02T00:00:00Z', summary: 'boom' },
        ]);
        renderTaskPage();
        const heading = await screen.findByRole('heading', { name: 'My task' });
        // The header row must not carry a "Failed" status badge in the corner.
        const headerRow = heading.parentElement;
        expect(headerRow.textContent).not.toMatch(/Failed/);
    });

    it('shows the run info inline on the main page (not behind a tab)', async () => {
        api.forge.listTaskRuns.mockResolvedValue([
            { id: 'r1', status: 'completed', created_at: '2026-06-02T00:00:00Z', summary: 'all done' },
        ]);
        renderTaskPage();
        await screen.findByText('My task');
        expect(await screen.findByText('all done')).toBeInTheDocument();
    });

    it('organizes the full page into overview and collaboration bands', async () => {
        renderTaskPage();
        await screen.findByText('My task');

        const overview = screen.getByTestId('task-overview-section');
        const collaboration = screen.getByTestId('task-collaboration-section');

        expect(within(overview).getByText('Description')).toBeInTheDocument();
        expect(within(overview).getByText('Details')).toBeInTheDocument();
        expect(within(overview).getByText('How this fits in')).toBeInTheDocument();
        expect(within(collaboration).getByText('Comments')).toBeInTheDocument();
        expect(within(collaboration).getByText('Definition of Done')).toBeInTheDocument();
        expect(within(collaboration).getByText('Branch & PR')).toBeInTheDocument();
        expect(within(collaboration).getByText('Attachments')).toBeInTheDocument();
        expect(within(collaboration).getByText('Timestamps')).toBeInTheDocument();
    });

    it('exposes an Edit affordance and reveals editable core + detail fields', async () => {
        renderTaskPage();
        await screen.findByText('My task');
        fireEvent.click(screen.getByTitle('Edit task'));

        expect(screen.getByLabelText('Title').value).toBe('My task');
        expect(screen.getByLabelText('Description').value).toBe('the original description');
        expect(screen.getByLabelText('Status').value).toBe('todo');
        expect(screen.getByLabelText('Priority').value).toBe('medium');
        expect(screen.getByLabelText('Tags').value).toBe('alpha');
    });

    it('saves edited details, tags and status', async () => {
        renderTaskPage();
        await screen.findByText('My task');
        fireEvent.click(screen.getByTitle('Edit task'));

        fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Renamed' } });
        fireEvent.change(screen.getByLabelText('Priority'), { target: { value: 'high' } });
        fireEvent.change(screen.getByLabelText('Tags'), { target: { value: 'alpha, beta' } });
        fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'in_progress' } });
        fireEvent.click(screen.getByRole('button', { name: /save/i }));

        await waitFor(() => expect(api.updateTask).toHaveBeenCalledWith(
            'T1',
            expect.objectContaining({
                title: 'Renamed',
                priority: 'high',
                tags: ['alpha', 'beta'],
            }),
        ));
        expect(api.moveTask).toHaveBeenCalledWith('T1', 'in_progress');
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

    it('can start an agent run from the main page (regression guard)', async () => {
        renderTaskPage();
        await screen.findByText('My task');

        fireEvent.click(await screen.findByRole('button', { name: /run with agent/i }));
        fireEvent.click(await screen.findByText('Implementer'));

        await waitFor(() =>
            expect(api.forge.prepareTaskRun).toHaveBeenCalledWith('T1', 'a1'));
    });
});
