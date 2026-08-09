import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { MyWork } from './MyWork';
import { api } from '../api';

vi.mock('../api', () => ({
    api: { listTasks: vi.fn() },
}));

vi.mock('../context/AuthContext', () => ({
    useAuth: () => ({ user: { name: 'alice', display_name: 'Alice' } }),
}));

const TASKS = [
    { id: 't1', key: 'AP-1', title: 'Fix the thing', status: 'in_progress', priority: 'high' },
    { id: 't2', key: 'AP-2', title: 'Write the docs', status: 'todo', priority: 'low' },
];

function renderMyWork() {
    return render(
        <MemoryRouter initialEntries={['/studio/my-work']}>
            <Routes>
                <Route path="/studio/my-work" element={<MyWork />} />
                <Route path="/studio/tasks/:taskId" element={<div>TASK DETAIL</div>} />
            </Routes>
        </MemoryRouter>,
    );
}

describe('MyWork page', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.listTasks.mockResolvedValue(TASKS);
    });

    it('queries tasks assigned to the current user', async () => {
        renderMyWork();
        await screen.findByText('Fix the thing');
        expect(api.listTasks).toHaveBeenCalledWith(null, null, 'alice');
    });

    it('groups tasks by status', async () => {
        renderMyWork();
        expect(await screen.findByText('Fix the thing')).toBeInTheDocument();
        expect(screen.getByText('in progress')).toBeInTheDocument();
        expect(screen.getByText('todo')).toBeInTheDocument();
    });

    it('clicking a task navigates to its detail page', async () => {
        renderMyWork();
        fireEvent.click(await screen.findByText('Fix the thing'));
        expect(await screen.findByText('TASK DETAIL')).toBeInTheDocument();
    });

    it('shows an empty state when nothing is assigned', async () => {
        api.listTasks.mockResolvedValue([]);
        renderMyWork();
        expect(await screen.findByText(/Nothing assigned to you yet/)).toBeInTheDocument();
    });
});
