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

function renderBacklog() {
    return render(
        <MemoryRouter initialEntries={['/studio/project/P1/backlog']}>
            <Routes>
                <Route
                    path="/studio/project/:projectId"
                    element={<Outlet context={{ requestSelectTask: () => {} }} />}
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
});
