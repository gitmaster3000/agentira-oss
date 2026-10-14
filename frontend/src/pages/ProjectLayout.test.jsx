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

    it('shows a Home / project breadcrumb on Overview only, and the description moves to the page', async () => {
        api.getBoard.mockResolvedValue({ project: { id: 'p1', name: 'Atlas', key_prefix: 'ATL', description: 'Maps for everyone' }, columns: {} });
        mount('/studio/project/p1/overview');
        const crumb = await screen.findByRole('navigation', { name: 'Breadcrumb' });
        expect(crumb).toHaveTextContent('Home');
        expect(screen.getByRole('link', { name: 'Home' })).toHaveAttribute('href', '/studio');
        expect(screen.queryByText('Maps for everyone')).not.toBeInTheDocument();
    });

    it('loads the feed once (limit 20), then polls with limit=1 and refetches 20 only when the newest id changes', async () => {
        api.getProjectActivity.mockImplementation((_p, limit) =>
            Promise.resolve(limit === 1 ? [{ id: 'a1' }] : [{ id: 'a1' }, { id: 'a0' }]));
        vi.useFakeTimers({ shouldAdvanceTime: true });
        try {
            mount('/studio/project/p1/board');
            await screen.findByText('ATL');
            expect(api.getProjectActivity).toHaveBeenCalledWith('p1', 20);
            api.getProjectActivity.mockClear();
            // newest id unchanged -> poll is limit=1 only
            await vi.advanceTimersByTimeAsync(30000);
            expect(api.getProjectActivity.mock.calls).toEqual([['p1', 1]]);
            // new entry -> limit=1 then one limit=20 refresh
            api.getProjectActivity.mockClear();
            api.getProjectActivity.mockImplementation((_p, limit) =>
                Promise.resolve(limit === 1 ? [{ id: 'a2' }] : [{ id: 'a2' }, { id: 'a1' }]));
            await vi.advanceTimersByTimeAsync(30000);
            expect(api.getProjectActivity.mock.calls).toEqual([['p1', 1], ['p1', 20]]);
        } finally {
            vi.useRealTimers();
        }
    });
});
