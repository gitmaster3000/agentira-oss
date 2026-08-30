import React, { useState } from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { TaskDetailPanel } from './TaskDetailPanel';
import { api } from '../api';

vi.mock('../api', () => ({
    api: {
        getActivity: vi.fn(() => Promise.resolve([])),
        listAttachments: vi.fn(() => Promise.resolve([])),
        uploadAttachment: vi.fn(() => Promise.resolve({})),
        deleteAttachment: vi.fn(() => Promise.resolve({})),
        listTaskCommits: vi.fn(() => Promise.resolve([])),
        getProjectMembers: vi.fn(() => Promise.resolve([])),
        getEpics: vi.fn(() => Promise.resolve([])),
        listSubtasks: vi.fn(() => Promise.resolve([])),
        listTasks: vi.fn(() => Promise.resolve([])),
        listMilestones: vi.fn(() => Promise.resolve([])),
        moveTask: vi.fn(() => Promise.resolve({})),
        updateTask: vi.fn(() => Promise.resolve({})),
        forge: { listTaskRuns: vi.fn(() => Promise.resolve([])) },
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
        description: 'desc',
        status: 'todo',
        priority: 'medium',
        assignee: '',
        dod_items: [],
        branch: 'feature/old',
        pr_url: 'https://github.com/acme/web/pull/7',
        repo_name: '',
        repos: [],
        project_id: 'P1',
        ...overrides,
    };
}

// Wrapper drives isEditing the same way the parent pages do.
function Harness({ task, onSelectTask }) {
    const [isEditing, setIsEditing] = useState(false);
    return (
        <MemoryRouter>
            <TaskDetailPanel
                task={task}
                onClose={() => {}}
                onUpdate={() => {}}
                onSelectTask={onSelectTask}
                isEditing={isEditing}
                setIsEditing={setIsEditing}
            />
        </MemoryRouter>
    );
}

describe('TaskDetailPanel — edit mode Branch & PR', () => {
    beforeEach(() => vi.clearAllMocks());

    it('renders Branch and PR as editable inputs in edit mode', async () => {
        render(<Harness task={baseTask()} />);
        fireEvent.click(await screen.findByTitle('Edit'));

        const branch = screen.getByLabelText('Branch');
        const pr = screen.getByLabelText('Pull Request');
        expect(branch).toBeInTheDocument();
        expect(branch.value).toBe('feature/old');
        expect(pr.value).toBe('https://github.com/acme/web/pull/7');
    });

    it('saves edited Branch and PR via updateTask on Save', async () => {
        render(<Harness task={baseTask()} />);
        fireEvent.click(await screen.findByTitle('Edit'));

        fireEvent.change(screen.getByLabelText('Branch'), { target: { value: 'feature/new' } });
        fireEvent.change(screen.getByLabelText('Pull Request'), { target: { value: 'https://github.com/acme/web/pull/9' } });
        fireEvent.click(screen.getByRole('button', { name: /save/i }));

        await waitFor(() => expect(api.updateTask).toHaveBeenCalledWith(
            'T1',
            expect.objectContaining({
                branch: 'feature/new',
                pr_url: 'https://github.com/acme/web/pull/9',
            }),
        ));
    });

    it('reflects Branch & PR after a post-save refetch (same task id)', async () => {
        const { rerender } = render(<Harness task={baseTask({ branch: 'feature/old', pr_url: '' })} />);
        expect(await screen.findByText('feature/old')).toBeInTheDocument();

        // Parent refetches the same task with the saved values.
        rerender(<Harness task={baseTask({ branch: 'feature/new', pr_url: 'https://github.com/acme/web/pull/9' })} />);

        expect(await screen.findByText('feature/new')).toBeInTheDocument();
        expect(screen.queryByText('feature/old')).not.toBeInTheDocument();
        expect(screen.getByText('web#9')).toBeInTheDocument();
    });

    it('Cancel reverts edits without calling updateTask', async () => {
        render(<Harness task={baseTask()} />);
        fireEvent.click(await screen.findByTitle('Edit'));

        fireEvent.change(screen.getByLabelText('Branch'), { target: { value: 'feature/throwaway' } });
        fireEvent.click(screen.getByRole('button', { name: /cancel/i }));

        expect(api.updateTask).not.toHaveBeenCalled();
        // Back to read-only display showing the original branch.
        expect(screen.queryByLabelText('Branch')).not.toBeInTheDocument();
    });

    it('hides the standalone close (X) in edit mode — Cancel covers it', async () => {
        render(<Harness task={baseTask()} />);
        expect(screen.getByTitle('Close')).toBeInTheDocument();

        fireEvent.click(await screen.findByTitle('Edit'));
        expect(screen.queryByTitle('Close')).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument();
    });

    it('shows the epic as a dropdown in the details rows (like assignee)', async () => {
        api.getEpics.mockResolvedValue([
            { id: 'E1', title: 'Onboarding' },
            { id: 'E2', title: 'Billing' },
        ]);
        render(<Harness task={baseTask({ epic_id: 'E1', epic_name: 'Onboarding', epic_color: '#7c4dff' })} />);

        const select = await screen.findByLabelText('Epic');
        expect(select.tagName).toBe('SELECT');
        await waitFor(() => expect(select.value).toBe('E1'));
        // Options come from the project's epics.
        expect(screen.getByRole('option', { name: 'Billing' })).toBeInTheDocument();
    });

    it('saves the epic via updateTask when the dropdown changes (no edit mode)', async () => {
        api.getEpics.mockResolvedValue([{ id: 'E1', title: 'Onboarding' }]);
        render(<Harness task={baseTask()} />);

        const select = await screen.findByLabelText('Epic');
        await waitFor(() => expect(screen.getByRole('option', { name: 'Onboarding' })).toBeInTheDocument());
        fireEvent.change(select, { target: { value: 'E1' } });

        await waitFor(() => expect(api.updateTask).toHaveBeenCalledWith(
            'T1', expect.objectContaining({ epic_id: 'E1' }),
        ));
    });

    it('shows the repo a multi-repo task maps its Branch & PR to', async () => {
        render(<Harness task={baseTask({ repo_name: 'frontend', repos: ['frontend', 'backend'] })} />);
        expect(await screen.findByText('frontend')).toBeInTheDocument();
        expect(screen.getByText(/apply to this repo/i)).toBeInTheDocument();
    });
});

describe('TaskDetailPanel — layout & resizing', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        localStorage.clear();
    });

    it('places Description below the Status/Priority/Assignee/Epic fields', async () => {
        const { container } = render(<Harness task={baseTask()} />);
        const label = await screen.findByText('Description');
        const epic = screen.getByLabelText('Epic');
        expect(
            label.compareDocumentPosition(epic) & Node.DOCUMENT_POSITION_PRECEDING,
        ).toBeTruthy();
        expect(container).toBeTruthy();
    });

    it('makes each side-panel section collapsible', async () => {
        render(<Harness task={baseTask()} />);
        const filesToggle = await screen.findByRole('button', { name: 'Toggle Files section' });

        expect(filesToggle).toHaveAttribute('aria-expanded', 'true');
        fireEvent.click(filesToggle);
        expect(filesToggle).toHaveAttribute('aria-expanded', 'false');
        expect(screen.queryByText('Attach a file')).not.toBeInTheDocument();
    });

    it('shows planning relationships and only exposes their controls in edit mode', async () => {
        const onSelectTask = vi.fn();
        api.listSubtasks.mockResolvedValueOnce([
            { id: 'T2', key: 'AP-2', title: 'Child work', status: 'todo' },
        ]);
        render(<Harness task={baseTask()} onSelectTask={onSelectTask} />);

        expect(await screen.findByText('Child work')).toBeInTheDocument();
        expect(screen.queryByTitle('Add a subtask')).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'AP-2' }));
        expect(onSelectTask).toHaveBeenCalledWith('T2');

        fireEvent.click(screen.getByTitle('Edit'));
        expect(screen.getByTitle('Add a subtask')).toBeInTheDocument();
    });

    it('resizes by dragging the divider and remembers the width', async () => {
        render(<Harness task={baseTask()} />);
        const panel = await screen.findByRole('complementary');
        expect(panel.style.width).toBe('384px');

        const handle = screen.getByRole('separator', { name: /resize/i });
        fireEvent.mouseDown(handle, { clientX: 800 });
        fireEvent.mouseMove(document, { clientX: 700 });
        expect(panel.style.width).toBe('484px');

        fireEvent.mouseUp(document);
        expect(localStorage.getItem('taskPanelWidth')).toBe('484');
    });

    it('clamps the dragged width to the allowed range', async () => {
        render(<Harness task={baseTask()} />);
        const panel = await screen.findByRole('complementary');
        const handle = screen.getByRole('separator', { name: /resize/i });

        fireEvent.mouseDown(handle, { clientX: 800 });
        fireEvent.mouseMove(document, { clientX: 5000 });
        expect(panel.style.width).toBe('320px');
        fireEvent.mouseUp(document);
    });

    it('restores a previously saved width', async () => {
        localStorage.setItem('taskPanelWidth', '520');
        render(<Harness task={baseTask()} />);
        const panel = await screen.findByRole('complementary');
        expect(panel.style.width).toBe('520px');
    });
});

describe('TaskDetailPanel — typed test evidence', () => {
    beforeEach(() => vi.clearAllMocks());

    it('groups evidence and uploads with the selected kind', async () => {
        api.listAttachments.mockResolvedValue([
            { id: 'A1', filename: 'acceptance.md', kind: 'test-report' },
            { id: 'A2', filename: 'notes.txt', kind: 'other' },
        ]);
        const { container } = render(<Harness task={baseTask()} />);

        expect(await screen.findByText('Test evidence')).toBeInTheDocument();
        expect(screen.getByText('Other files')).toBeInTheDocument();
        expect(screen.getAllByText('Test report')).toHaveLength(2);

        fireEvent.change(screen.getByLabelText('Attachment kind'), {
            target: { value: 'recording' },
        });
        const input = container.querySelector('input[type="file"]');
        const file = new File(['video'], 'acceptance.webm', {
            type: 'video/webm',
        });
        fireEvent.change(input, { target: { files: [file] } });

        await waitFor(() => expect(api.uploadAttachment).toHaveBeenCalledWith(
            'T1', file, 'recording',
        ));
    });
});

describe('TaskDetailPanel — due date (AP-501)', () => {
    beforeEach(() => vi.clearAllMocks());

    it('shows due date in the Details section and saves on change', async () => {
        render(<Harness task={baseTask({ due_date: '2026-08-20T00:00:00Z' })} />);
        const due = await screen.findByLabelText('Due date');
        expect(due.value).toBe('2026-08-20');

        fireEvent.change(due, { target: { value: '2026-09-01' } });
        await waitFor(() => expect(api.updateTask).toHaveBeenCalledWith(
            'T1',
            expect.objectContaining({ due_date: '2026-09-01' }),
        ));
    });

    it('clears due date when the date input is emptied', async () => {
        render(<Harness task={baseTask({ due_date: '2026-08-20T00:00:00Z' })} />);
        const due = await screen.findByLabelText('Due date');
        fireEvent.change(due, { target: { value: '' } });
        await waitFor(() => expect(api.updateTask).toHaveBeenCalledWith(
            'T1',
            expect.objectContaining({ due_date: '' }),
        ));
    });
});
