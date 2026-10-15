import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route, Link } from 'react-router-dom';
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
        getTaskProof: vi.fn(() => Promise.resolve({ present: false, stale: false })),
        listSubtasks: vi.fn(() => Promise.resolve([])),
        listTasks: vi.fn(() => Promise.resolve([])),
        listMilestones: vi.fn(() => Promise.resolve([])),
        listTaskLinks: vi.fn(() => Promise.resolve([])),
        updateTask: vi.fn(() => Promise.resolve({})),
        forge: { listTaskRuns: vi.fn(() => Promise.resolve([])) },
    },
}));
const authValue = vi.hoisted(() => ({ user: { display_name: 'Tester' } }));
vi.mock('../context/AuthContext', () => ({ useAuth: () => authValue }));
vi.mock('../components/shell/shellData', () => ({
    useShellData: () => ({ projects: [{ id: 'P1', name: 'Acme Board' }] }),
}));

const task = {
    id: 'T1', key: 'AP-1', title: 'My task', description: 'the original description', status: 'todo',
    priority: 'medium', assignee: '', dod_items: [], tags: [], branch: '', pr_url: '', repos: [],
    project_id: 'P1', created_at: '2026-06-01T00:00:00Z', updated_at: '2026-06-01T00:00:00Z',
};

function renderPage() {
    render(
        <MemoryRouter initialEntries={['/studio/tasks/T1']}>
            <Routes><Route path="/studio/tasks/:taskId" element={<TaskPage />} /></Routes>
        </MemoryRouter>,
    );
}
const tab = (name) => fireEvent.click(screen.getByRole('button', { name }));

describe('TaskPage — drafts survive a tab switch', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.getTask.mockResolvedValue(task);
    });

    it('keeps a half-written comment', async () => {
        renderPage();
        const box = await screen.findByPlaceholderText(/Add a comment/);
        fireEvent.change(box, { target: { value: 'half-written' } });
        tab(/^run$/i);
        expect(screen.queryByPlaceholderText(/Add a comment/)).toBeNull();
        tab(/^plan$/i);
        expect(screen.getByPlaceholderText(/Add a comment/).value).toBe('half-written');
    });

    it('shows the typed description after switching tabs, and Save writes that same text', async () => {
        renderPage();
        fireEvent.click(await screen.findByTitle('Edit task'));
        fireEvent.change(screen.getByLabelText('Description'), { target: { value: 'new body' } });
        tab(/^run$/i);
        tab(/^plan$/i);
        expect(screen.getByLabelText('Description').value).toBe('new body');
        fireEvent.click(screen.getByTitle('Save changes'));
        await waitFor(() => expect(api.updateTask).toHaveBeenCalledWith(
            'T1', expect.objectContaining({ description: 'new body' }),
        ));
    });
});

describe('TaskPage — Create Task header', () => {
    it('names the project when opened from the task page', async () => {
        api.getTask.mockResolvedValue(task);
        renderPage();
        await screen.findByText('My task');
        window.dispatchEvent(new Event('open-create-task'));
        expect(await screen.findByText('in Acme Board')).toBeInTheDocument();
    });
});

describe('TaskPage — switching task', () => {
    const task2 = { ...task, id: 'T2', key: 'AP-2', title: 'Other task', description: 'other body', tags: [] };
    beforeEach(() => {
        vi.clearAllMocks();
        api.getTask.mockImplementation((id) => Promise.resolve(id === 'T2' ? task2 : task));
    });
    function renderTwo() {
        render(
            <MemoryRouter initialEntries={['/studio/tasks/T1']}>
                <Link to="/studio/tasks/T2">go-two</Link>
                <Routes><Route path="/studio/tasks/:taskId" element={<TaskPage />} /></Routes>
            </MemoryRouter>,
        );
    }

    it('shows an empty composer on the new task and submits only there', async () => {
        api.addComment = vi.fn(() => Promise.resolve({}));
        renderTwo();
        fireEvent.change(await screen.findByPlaceholderText(/Add a comment/), { target: { value: 'for task one' } });
        fireEvent.click(screen.getByText('go-two'));
        await screen.findByText('Other task');
        const box = screen.getByPlaceholderText(/Add a comment/);
        expect(box.value).toBe('');
        fireEvent.change(box, { target: { value: 'for two' } });
        fireEvent.submit(box.closest('form'));
        await waitFor(() => expect(api.addComment).toHaveBeenCalled());
        expect(api.addComment.mock.calls[0][0]).toBe('T2');
        expect(api.addComment.mock.calls[0][1]).toEqual({ comment: 'for two' });
    });

    it('leaves edit mode on switch; Save writes the new task values only', async () => {
        renderTwo();
        fireEvent.click(await screen.findByTitle('Edit task'));
        fireEvent.change(screen.getByLabelText('Description'), { target: { value: 'typed on one' } });
        fireEvent.click(screen.getByText('go-two'));
        await screen.findByText('Other task');
        expect(screen.queryByTitle('Save changes')).toBeNull();
        fireEvent.click(screen.getByTitle('Edit task'));
        expect(screen.getByLabelText('Description').value).toBe('other body');
        fireEvent.click(screen.getByTitle('Save changes'));
        await waitFor(() => expect(api.updateTask).toHaveBeenCalled());
        const [id, body] = api.updateTask.mock.calls[0];
        expect(id).toBe('T2');
        expect(body).toMatchObject({ title: 'Other task', description: 'other body' });
    });
});
