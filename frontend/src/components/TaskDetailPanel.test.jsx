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
        listTaskCommits: vi.fn(() => Promise.resolve([])),
        getProjectMembers: vi.fn(() => Promise.resolve([])),
        getEpics: vi.fn(() => Promise.resolve([])),
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
function Harness({ task }) {
    const [isEditing, setIsEditing] = useState(false);
    return (
        <MemoryRouter>
            <TaskDetailPanel
                task={task}
                onClose={() => {}}
                onUpdate={() => {}}
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
