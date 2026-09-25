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
        listTaskLinks: vi.fn(() => Promise.resolve([])),
        addTaskLink: vi.fn(() => Promise.resolve({})),
        removeTaskLink: vi.fn(() => Promise.resolve({ ok: true })),
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

    it('offers a Run tab beside Activity', async () => {
        renderTaskPage();
        await screen.findByText('My task');
        expect(screen.getByRole('button', { name: /^plan$/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /^run$/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /^activity$/i })).toBeInTheDocument();
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

    it('keeps run info on the Run tab, out of the Plan tab', async () => {
        api.forge.listTaskRuns.mockResolvedValue([
            { id: 'r1', status: 'completed', created_at: '2026-06-02T00:00:00Z', summary: 'all done' },
        ]);
        renderTaskPage();
        await screen.findByText('My task');
        expect(screen.queryByText('all done')).toBeNull();

        fireEvent.click(screen.getByRole('button', { name: /^run$/i }));
        expect(await screen.findByText('all done')).toBeInTheDocument();
        expect(screen.queryByTestId('task-overview-section')).toBeNull();
    });

    const INFO_SECTIONS = ['Details', 'Links', 'Definition of Done', 'Branch & PR', 'Files', 'Timestamps'];

    it('bounds the top band and pools every non-description section in one pane', async () => {
        renderTaskPage();
        await screen.findByText('My task');

        const overview = screen.getByTestId('task-overview-section');
        const pane = within(overview).getByTestId('task-info-pane');

        // The brief keeps its own pane; everything else shares the scroller.
        expect(within(overview).getByText('Description')).toBeInTheDocument();
        expect(within(pane).queryByText('Description')).toBeNull();

        // One contiguous panel — the sections are siblings, not stacked cards.
        const sectionOf = (label) => within(pane).getByText(label).closest('section');
        for (const label of INFO_SECTIONS) {
            expect(sectionOf(label)).not.toBeNull();
            expect(sectionOf(label).parentElement).toBe(sectionOf('Details').parentElement);
        }
    });

    it('collapses and expands an info section', async () => {
        renderTaskPage();
        await screen.findByText('My task');

        const pane = screen.getByTestId('task-info-pane');
        expect(within(pane).getByText('Timestamps')).toBeInTheDocument();
        expect(within(pane).getByTestId('task-due-date')).toBeInTheDocument();

        fireEvent.click(within(pane).getByRole('button', { name: /toggle timestamps section/i }));
        expect(within(pane).queryByTestId('task-due-date')).toBeNull();

        fireEvent.click(within(pane).getByRole('button', { name: /toggle timestamps section/i }));
        expect(within(pane).getByTestId('task-due-date')).toBeInTheDocument();
    });

    it('pins the title and tabs while the page scrolls', async () => {
        renderTaskPage();
        await screen.findByText('My task');

        const header = screen.getByTestId('task-page-header');
        expect(header.className).toMatch(/\bsticky\b/);
        expect(header.className).toMatch(/\btop-0\b/);
        expect(within(header).getByRole('heading', { name: 'My task' })).toBeInTheDocument();
        expect(within(header).getByRole('button', { name: /^plan$/i })).toBeInTheDocument();
        expect(within(header).getByRole('button', { name: /^activity$/i })).toBeInTheDocument();
    });

    it('keeps comments in the Plan tab, below the bounded band', async () => {
        renderTaskPage();
        await screen.findByText('My task');

        // Not a tab of its own — a section under the overview band.
        expect(screen.queryByRole('button', { name: /^comments$/i })).toBeNull();
        const collaboration = screen.getByTestId('task-collaboration-section');
        expect(within(collaboration).getByText('Comments')).toBeInTheDocument();
        expect(
            screen.getByTestId('task-overview-section')
                .compareDocumentPosition(collaboration) & Node.DOCUMENT_POSITION_FOLLOWING,
        ).toBeTruthy();
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

    it('shows due date in Timestamps and saves it from edit mode (AP-501)', async () => {
        api.getTask.mockResolvedValue(baseTask({ due_date: '2026-09-15T00:00:00Z' }));
        renderTaskPage();
        await screen.findByText('My task');

        const pane = screen.getByTestId('task-info-pane');
        expect(within(pane).getByText('Timestamps')).toBeInTheDocument();
        // Read mode shows the existing due date (locale-formatted).
        expect(within(pane).getByTestId('task-due-date').textContent).toMatch(/9\/15\/2026|15\/9\/2026|2026/);

        fireEvent.click(screen.getByTitle('Edit task'));
        const dueInput = screen.getByLabelText('Due date');
        expect(dueInput.value).toBe('2026-09-15');
        fireEvent.change(dueInput, { target: { value: '2026-10-01' } });
        fireEvent.click(screen.getByRole('button', { name: /save/i }));

        await waitFor(() => expect(api.updateTask).toHaveBeenCalledWith(
            'T1',
            expect.objectContaining({ due_date: '2026-10-01' }),
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

    it('can start an agent run from the Run tab (regression guard)', async () => {
        renderTaskPage();
        await screen.findByText('My task');

        fireEvent.click(screen.getByRole('button', { name: /^run$/i }));
        fireEvent.click(await screen.findByRole('button', { name: /run with agent/i }));
        fireEvent.click(await screen.findByText('Implementer'));

        await waitFor(() =>
            expect(api.forge.prepareTaskRun).toHaveBeenCalledWith('T1', 'a1'));
    });
});
