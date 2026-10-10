import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route, Outlet } from 'react-router-dom';
import { Backlog } from './Backlog';
import { api } from '../api';

vi.mock('../api', () => ({
    api: {
        getEpics: vi.fn(),
        listTasks: vi.fn(),
        getProjectActivity: vi.fn(() => Promise.resolve([])),
    },
}));

function renderBacklog(searchQuery) {
    return render(
        <MemoryRouter initialEntries={['/studio/project/P1/backlog']}>
            <Routes>
                <Route
                    path="/studio/project/:projectId"
                    element={<Outlet context={{ requestSelectTask: () => {}, searchQuery }} />}
                >
                    <Route path="backlog" element={<Backlog />} />
                </Route>
                <Route path="/studio/epics/:id" element={<div>EPIC DETAIL PAGE</div>} />
            </Routes>
        </MemoryRouter>,
    );
}

describe('Backlog epic sections', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.getEpics.mockResolvedValue([{ id: 'E1', title: 'Login Epic', color: '#7c4dff' }]);
        api.listTasks.mockResolvedValue([
            { id: 'T1', key: 'AP-1', title: 'Task one', status: 'todo', epic_id: 'E1', priority: 'high' },
        ]);
    });

    it('renders the epic section header as a link to the epic detail page', async () => {
        renderBacklog();
        const link = await screen.findByRole('link', { name: /Login Epic/i });
        expect(link).toHaveAttribute('href', '/studio/epics/E1');
    });

    it('navigates to the epic detail page when the header is clicked', async () => {
        renderBacklog();
        const link = await screen.findByRole('link', { name: /Login Epic/i });
        fireEvent.click(link);
        await waitFor(() => expect(screen.getByText('EPIC DETAIL PAGE')).toBeInTheDocument());
    });

    it('hides empty epic sections while a search is active', async () => {
        api.getEpics.mockResolvedValue([
            { id: 'E1', title: 'Login Epic', color: '#7c4dff' },
            { id: 'E2', title: 'Empty Epic', color: '#00bcd4' },
        ]);
        api.listTasks.mockResolvedValue([
            { id: 'T1', key: 'AP-1', title: 'Task one', status: 'todo', epic_id: 'E1', priority: 'high' },
            { id: 'T2', key: 'AP-2', title: 'Task two', status: 'todo', epic_id: null, priority: 'low' },
        ]);
        renderBacklog('AP-2');
        await screen.findByText('Task two');
        expect(screen.queryByText('Task one')).not.toBeInTheDocument();
        expect(screen.queryByText(/Login Epic/)).not.toBeInTheDocument();
        expect(screen.queryByText(/Empty Epic/)).not.toBeInTheDocument();
    });
});
