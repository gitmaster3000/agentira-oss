import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { ProjectOverview } from './ProjectOverview';
import { api } from '../api';

vi.mock('../api', () => ({
    api: {
        getProject: vi.fn(),
        getProjectMembers: vi.fn(),
        listProjectRepos: vi.fn(),
        getBoard: vi.fn(),
        getProjectActivity: vi.fn(),
        listProjectAttachments: vi.fn(),
        // ProjectActivityPanel (live board strip) polls this.
        forge: { getProjectActivity: vi.fn(() => Promise.resolve(null)) },
    },
}));

const ACTIVITY = [
    {
        id: 'a1',
        task_id: 'cb344582f4f9',
        actor: 'Frontend Developer',
        action: 'commented',
        // markdown with an internal run link + an external PR url
        detail:
            '✅ **Run succeeded** ([run df896c2d](/forge/runs/df896c2d029a)) — PR ' +
            'https://github.com/acme/agentira-frontend/pull/70',
        created_at: '2026-06-07T17:05:34.925999',
    },
    {
        id: 'a2',
        task_id: '86192db52477',
        actor: 'admin',
        action: 'task.move',
        detail: 'in_progress → review',
        created_at: '2026-06-07T18:37:00.804237',
    },
];

function renderOverview() {
    return render(
        <MemoryRouter initialEntries={['/studio/project/P1/overview']}>
            <Routes>
                <Route path="/studio/project/:projectId/overview" element={<ProjectOverview />} />
            </Routes>
        </MemoryRouter>,
    );
}

describe('ProjectOverview — recent activity feed', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.getProject.mockResolvedValue({ id: 'P1', name: 'Proj' });
        api.getProjectMembers.mockResolvedValue([]);
        api.listProjectRepos.mockResolvedValue([]);
        api.getBoard.mockResolvedValue({ columns: {} });
        api.listProjectAttachments.mockResolvedValue([]);
        api.getProjectActivity.mockResolvedValue(ACTIVITY);
    });

    it('renders activity entries with actor and human action label', async () => {
        renderOverview();
        expect(await screen.findByText('Frontend Developer')).toBeInTheDocument();
        // raw action "task.move" is shown as the friendly label "moved task"
        expect(screen.getByText('moved task')).toBeInTheDocument();
    });

    it('links each entry to its task page', async () => {
        renderOverview();
        const taskLink = await screen.findByRole('link', { name: /#cb344582/i });
        expect(taskLink).toHaveAttribute('href', '/studio/tasks/cb344582f4f9');
    });

    it('renders an internal run link as an SPA route (relative href, no new tab)', async () => {
        renderOverview();
        const runLink = await screen.findByRole('link', { name: /run df896c2d/i });
        expect(runLink).toHaveAttribute('href', '/forge/runs/df896c2d029a');
        expect(runLink).not.toHaveAttribute('target');
    });

    it('renders an external PR url as a new-tab link', async () => {
        renderOverview();
        const prLink = await screen.findByRole('link', {
            name: /github\.com\/acme\/agentira-frontend\/pull\/70/i,
        });
        expect(prLink).toHaveAttribute('target', '_blank');
        expect(prLink.getAttribute('href')).toContain('/pull/70');
    });

    it('fetches a fuller activity window (limit 20)', async () => {
        renderOverview();
        await waitFor(() => expect(api.getProjectActivity).toHaveBeenCalled());
        expect(api.getProjectActivity).toHaveBeenCalledWith('P1', 20);
    });

    it('does not render the old redundant quick-link nav (Board/Backlog/Roadmap cards)', async () => {
        renderOverview();
        await screen.findByText('Frontend Developer');
        expect(screen.queryByRole('link', { name: /^Board$/i })).toBeNull();
        expect(screen.queryByRole('link', { name: /^Roadmap$/i })).toBeNull();
    });

    it('renders status counts as clickable navigation', async () => {
        renderOverview();
        // Backlog count → Backlog page
        const backlogStat = await screen.findByRole('link', { name: /Backlog/i });
        expect(backlogStat).toHaveAttribute('href', '/studio/project/P1/backlog');
        // In progress count → Board
        const inProgressStat = screen.getByRole('link', { name: /In progress/i });
        expect(inProgressStat).toHaveAttribute('href', '/studio/project/P1/board');
    });
});

describe('ProjectOverview — Team & roles', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.getProject.mockResolvedValue({ id: 'P1', name: 'Proj' });
        api.getProjectMembers.mockResolvedValue([
            { id: 'm1', name: 'Frontend Developer', display_name: 'Frontend Developer', role: 'member' },
            { id: 'm2', name: 'planner', display_name: 'planner', role: 'member' },
        ]);
        api.listProjectRepos.mockResolvedValue([]);
        api.getBoard.mockResolvedValue({ columns: {} });
        api.listProjectAttachments.mockResolvedValue([]);
        api.getProjectActivity.mockResolvedValue([]);
    });

    it('infers a function badge per member', async () => {
        renderOverview();
        // "Frontend Developer" → Frontend, "planner" → Planner
        expect(await screen.findByText('Frontend')).toBeInTheDocument();
        expect(screen.getByText('Planner')).toBeInTheDocument();
    });

    it('expands a member to reveal their responsibilities', async () => {
        renderOverview();
        const planner = await screen.findByText('Planner');
        // blurb hidden until expanded
        expect(screen.queryByText(/shapes the backlog/i)).toBeNull();
        fireEvent.click(planner.closest('button'));
        expect(await screen.findByText(/shapes the backlog/i)).toBeInTheDocument();
    });
});
