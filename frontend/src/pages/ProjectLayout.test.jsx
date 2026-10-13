import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { ProjectLayout } from './ProjectLayout';
import { api } from '../api';

vi.mock('../api', () => ({
    api: {
        getBoard: vi.fn(),
        getProjectMembers: vi.fn(),
        getProfiles: vi.fn(),
        getEpics: vi.fn(),
        getProjectActivity: vi.fn(),
    },
}));

function mount(path) {
    return render(
        <MemoryRouter initialEntries={[path]}>
            <Routes>
                <Route path="/studio/project/:projectId" element={<ProjectLayout />}>
                    <Route path="board" element={<div>board-body</div>} />
                    <Route path="overview" element={<div>overview-body</div>} />
                    <Route path="deploy" element={<div>deploy-body</div>} />
                </Route>
            </Routes>
        </MemoryRouter>
    );
}

describe('ProjectLayout header', () => {
    beforeEach(() => {
        api.getBoard.mockResolvedValue({ project: { id: 'p1', name: 'Atlas', key_prefix: 'ATL' }, columns: {} });
        api.getProjectMembers.mockResolvedValue([]);
        api.getProfiles.mockResolvedValue([]);
        api.getEpics.mockResolvedValue([]);
        api.getProjectActivity.mockResolvedValue([]);
    });

    it('shows key badge, name, members and the tab bar with the active tab marked', async () => {
        mount('/studio/project/p1/board');
        expect(await screen.findByText('ATL')).toBeInTheDocument();
        expect(screen.getByText('Atlas')).toBeInTheDocument();
        expect(screen.getByText('Members')).toBeInTheDocument();
        const nav = screen.getByRole('navigation', { name: 'Project sections' });
        expect(nav.querySelectorAll('a, [aria-disabled]')).toHaveLength(10);
        expect(screen.getByRole('link', { name: 'Board' })).toHaveAttribute('aria-current', 'page');
        expect(screen.getByRole('link', { name: 'Backlog' })).toHaveAttribute('href', '/studio/project/p1/backlog');
        expect(screen.getByPlaceholderText('Search tasks…')).toBeInTheDocument();
    });

    it('keeps the tabs on non-board pages without the search box', async () => {
        mount('/studio/project/p1/deploy');
        expect(await screen.findByRole('link', { name: 'Deploy' })).toHaveAttribute('aria-current', 'page');
        expect(screen.queryByPlaceholderText('Search tasks…')).not.toBeInTheDocument();
    });

    it('shows the project description under the header on Overview only', async () => {
        api.getBoard.mockResolvedValue({ project: { id: 'p1', name: 'Atlas', key_prefix: 'ATL', description: 'Maps for everyone' }, columns: {} });
        mount('/studio/project/p1/overview');
        expect(await screen.findByText('Maps for everyone')).toBeInTheDocument();
    });
});
