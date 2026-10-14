import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route, Outlet } from 'react-router-dom';
import { ProjectOverview } from './ProjectOverview';
import { api } from '../api';

vi.mock('../api', () => ({
    api: { listMilestones: vi.fn() },
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

const DAY = 86400000;
const iso = (offsetDays) => new Date(Date.now() + offsetDays * DAY).toISOString();

const BOARD = {
    project: {
        id: 'P1', name: 'Proj', key_prefix: 'PR', description: 'Self-hosted **backlog** for the team.',
        repo_url: 'https://github.com/acme/agentira-oss.git', created_at: '2026-05-05T10:00:00',
    },
    columns: {
        backlog: [{ id: 't1', status: 'backlog', due_date: iso(-3), epic_id: 'E1' }],
        todo: [{ id: 't2', due_date: iso(2), epic_id: 'E1' }, { id: 't3' }],
        in_progress: [],
        review: [],
        done: [{ id: 't4', epic_id: 'E1' }, { id: 't5' }],
    },
};
const MEMBERS = [
    { id: 'm1', name: 'ali', display_name: 'Ali Faraz', roles: ['admin'], account_type: 'human' },
    { id: 'm2', name: 'impl', display_name: 'implementer-1', roles: ['member'], account_type: 'agentira_agent' },
    { id: 'm3', name: 'mo', display_name: 'Mohsin', roles: ['member'], account_type: 'human' },
];
const EPICS = [{ id: 'E1', title: 'Board UX', status: 'in_progress' }];

function renderOverview(ctx = {}) {
    const context = {
        board: BOARD, members: MEMBERS, epics: EPICS, activity: ACTIVITY,
        availableProfiles: [{ id: 'p9', name: 'newbie', display_name: 'Newbie' }],
        onAddMember: vi.fn(), ...ctx,
    };
    return {
        context,
        ...render(
            <MemoryRouter initialEntries={['/studio/project/P1/overview']}>
                <Routes>
                    <Route path="/studio/project/:projectId" element={<Outlet context={context} />}>
                        <Route path="overview" element={<ProjectOverview />} />
                    </Route>
                    <Route path="/studio/project/:projectId/settings" element={<div>settings-page</div>} />
                </Routes>
            </MemoryRouter>,
        ),
    };
}

describe('ProjectOverview', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.listMilestones.mockResolvedValue([
            { id: 'M1', title: 'Deploy that works', status: 'open', due_date: iso(5), total: 10, done: 2, progress: 20 },
            { id: 'M2', title: 'Seedbox', status: 'open', due_date: iso(60), total: 10, done: 6, progress: 60 },
        ]);
    });

    it('makes exactly one request of its own (milestones)', async () => {
        renderOverview();
        await screen.findByText('Milestones and epics');
        await waitFor(() => expect(api.listMilestones).toHaveBeenCalledTimes(1));
        expect(api.listMilestones).toHaveBeenCalledWith('P1');
    });

    it('shows the description at the top, rendered as markdown', async () => {
        renderOverview();
        expect(await screen.findByText('backlog', { selector: 'strong' })).toBeInTheDocument();
    });

    it('draws the four rings and the one-line summary from the loaded board', async () => {
        renderOverview();
        // 2 done, 3 open (backlog counts as open), 1 due this week, 1 late
        expect(await screen.findByRole('img', { name: 'Done: 2' })).toBeInTheDocument();
        expect(screen.getByRole('img', { name: 'Open: 3' })).toBeInTheDocument();
        expect(screen.getByRole('img', { name: 'Due this week: 1' })).toBeInTheDocument();
        expect(screen.getByRole('img', { name: 'Late: 1' })).toBeInTheDocument();
        expect(screen.getByText(/40% of 5 tasks done\. 1 task is late, and 1 is due this week\./)).toBeInTheDocument();
    });

    it('lists milestones and epics with progress, marking the at-risk ones', async () => {
        renderOverview();
        const risky = await screen.findByRole('progressbar', { name: 'Deploy that works' });
        expect(risky).toHaveAttribute('aria-valuenow', '20');
        expect(screen.getByText(/At risk · 2 of 10 done/)).toBeInTheDocument();
        expect(screen.queryByText(/At risk · 6 of 10/)).toBeNull();
        // epic has a late task, so it is at risk too; progress = 1 of 3 tasks done
        expect(screen.getByRole('progressbar', { name: 'Board UX' })).toHaveAttribute('aria-valuenow', '33');
        expect(screen.getByRole('link', { name: 'Board UX' })).toHaveAttribute('href', '/studio/epics/E1');
    });

    it('shows at most 5 milestones/epics, at-risk first, with a See all epics link', async () => {
        const many = Array.from({ length: 4 }, (_, i) => ({
            id: `X${i}`, title: `Calm ${i}`, status: 'open', due_date: iso(40 + i), total: 10, done: 5, progress: 50,
        }));
        api.listMilestones.mockResolvedValue([
            ...many,
            { id: 'R', title: 'Risky one', status: 'open', due_date: iso(-2), total: 4, done: 1, progress: 25 },
        ]);
        renderOverview();
        await waitFor(() => expect(screen.getAllByRole('progressbar')).toHaveLength(5));
        const bars = screen.getAllByRole('progressbar');
        expect(bars[0]).toHaveAttribute('aria-label', 'Risky one');
        expect(screen.getByRole('link', { name: /See all epics \(1 more\)/ }))
            .toHaveAttribute('href', '/studio/project/P1/epics');
    });

    it('shows About facts and routes Edit details to settings', async () => {
        renderOverview();
        expect(await screen.findByText('agentira-oss')).toBeInTheDocument();
        expect(screen.getByText('PR')).toBeInTheDocument();
        expect(screen.getAllByText('Ali Faraz').length).toBeGreaterThan(0);
        fireEvent.click(screen.getByRole('button', { name: 'Edit details' }));
        expect(await screen.findByText('settings-page')).toBeInTheDocument();
    });

    it('derives roles from account_type, not names (external agents are Agents too)', async () => {
        renderOverview({ members: [
            { id: 'a', name: 'admin-bot', display_name: 'Admin Bot', roles: ['admin'], account_type: 'external_agent' },
            { id: 'h', name: 'sam', display_name: 'Sam', roles: ['member'], account_type: 'human' },
        ] });
        await screen.findByText('Admin Bot');
        expect(screen.getByText('Agent')).toBeInTheDocument();
        expect(screen.getAllByText('Lead')).toHaveLength(2); // About label + Sam (only human -> lead)
        expect(screen.queryByText('Member')).toBeNull();
    });

    it('labels people Lead / Agent / Member', async () => {
        renderOverview();
        await screen.findByText('implementer-1');
        expect(screen.getAllByText('Lead')).toHaveLength(2); // About label + Ali's role
        expect(screen.getByText('Agent')).toBeInTheDocument();
        expect(screen.getByText('Member')).toBeInTheDocument();
    });

    it('Add people searches available profiles and adds via the layout handler', async () => {
        const { context } = renderOverview();
        fireEvent.click(await screen.findByRole('button', { name: 'Add people' }));
        fireEvent.change(screen.getByLabelText('Search people to add'), { target: { value: 'new' } });
        fireEvent.click(await screen.findByRole('button', { name: /Newbie/ }));
        expect(context.onAddMember).toHaveBeenCalledWith('newbie');
    });
});

describe('ProjectOverview — recent activity feed', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.listMilestones.mockResolvedValue([]);
    });

    it('renders activity entries with actor and human action label', async () => {
        renderOverview();
        expect(await screen.findByText('Frontend Developer')).toBeInTheDocument();
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
    });
});
