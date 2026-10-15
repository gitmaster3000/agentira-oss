import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route, Link } from 'react-router-dom';

const calls = vi.hoisted(() => ({ addComment: [], updateTask: [] }));
const tasks = vi.hoisted(() => ({
    T1: { id: 'T1', key: 'AP-1', title: 'First task', description: 'first body', status: 'todo', priority: 'medium', assignee: '', tags: [], dod_items: [], branch: 'branch-one', pr_url: '', repos: [], project_id: 'p1' },
    T2: { id: 'T2', key: 'AP-2', title: 'Second task', description: 'second body', status: 'todo', priority: 'medium', assignee: '', tags: [], dod_items: [], branch: 'branch-two', pr_url: '', repos: [], project_id: 'p1' },
}));

vi.mock('../api', () => {
    const impl = {
        getBoard: () => Promise.resolve({ project: { id: 'p1', name: 'Atlas', key_prefix: 'AP' }, columns: { todo: [tasks.T1, tasks.T2] } }),
        getTask: (id) => Promise.resolve(tasks[id]),
        addComment: (id, text) => { calls.addComment.push([id, text]); return Promise.resolve({}); },
        updateTask: (id, body) => { calls.updateTask.push([id, body]); return Promise.resolve({}); },
        forge: { listTaskRuns: () => Promise.resolve([]) },
    };
    return {
        api: new Proxy(impl, { get: (t, k) => (k in t ? t[k] : () => Promise.resolve([])) }),
    };
});
vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ user: { display_name: 'Tester' } }) }));

import { ProjectLayout } from './ProjectLayout';

function mount() {
    return render(
        <MemoryRouter initialEntries={['/studio/project/p1/board?selectedTask=T1']}>
            <Routes>
                <Route path="/studio/project/:projectId" element={<ProjectLayout />}>
                    <Route path="board" element={<Link to="?selectedTask=T2">open-second</Link>} />
                </Route>
            </Routes>
        </MemoryRouter>,
    );
}

describe('ProjectLayout side panel — switching task', () => {
    beforeEach(() => { calls.addComment.length = 0; calls.updateTask.length = 0; });

    it('starts the next task with an empty composer and posts only to that task', async () => {
        mount();
        const box = await screen.findByPlaceholderText(/Comment or @mention/);
        fireEvent.change(box, { target: { value: 'meant for task one' } });
        fireEvent.click(screen.getByText('open-second'));
        await screen.findByText('Second task');
        const next = screen.getByPlaceholderText(/Comment or @mention/);
        expect(next.value).toBe('');
        fireEvent.change(next, { target: { value: 'for two' } });
        fireEvent.submit(next.closest('form'));
        await waitFor(() => expect(calls.addComment.length).toBe(1));
        expect(calls.addComment[0][0]).toBe('T2');
        expect(calls.addComment[0][1]).toEqual({ comment: 'for two' });
    });

    it('drops an open edit when the task changes; Save then writes only the new task values', async () => {
        mount();
        fireEvent.click(await screen.findByTitle('Edit'));
        fireEvent.change(screen.getByLabelText('Branch'), { target: { value: 'typed-on-one' } });
        fireEvent.change(screen.getByDisplayValue('first body'), { target: { value: 'typed body' } });
        fireEvent.click(screen.getByText('open-second'));
        await screen.findByText('Second task');
        expect(screen.queryByLabelText('Branch')).toBeNull();
        fireEvent.click(screen.getByTitle('Edit'));
        expect(screen.getByLabelText('Branch').value).toBe('branch-two');
        expect(screen.getByDisplayValue('second body')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: /save/i }));
        await waitFor(() => expect(calls.updateTask.length).toBe(1));
        const [id, body] = calls.updateTask[0];
        expect(id).toBe('T2');
        expect(body).toMatchObject({ title: 'Second task', description: 'second body', branch: 'branch-two' });
    });
});
