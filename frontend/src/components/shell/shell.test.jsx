import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { AppSidebar } from './AppSidebar';
import { AppTopbar } from './AppTopbar';
import { ShellDataProvider } from './shellData';
import { api } from '../../api';
import { setCurrentProjectId } from '../../currentProject';

// The shell chrome is a port of Agentira.dc.html. These tests pin the two
// behaviours the design actually specifies — the rail's expanded/collapsed
// states, and the project switcher living in the top bar — plus the wiring
// that has to survive the port (navigation, project selection, live counts).

vi.mock('../../api', () => ({
    api: {
        getProjects: vi.fn(),
        getNotifications: vi.fn(),
        markNotificationRead: vi.fn(),
        forge: { listAgents: vi.fn(), listRuns: vi.fn() },
    },
}));

vi.mock('../../context/AuthContext', () => ({
    useAuth: () => ({ user: { display_name: 'Alex Rivera', role: 'Founder · admin' } }),
}));

vi.mock('../../currentProject', () => ({
    useCurrentProjectId: () => 'p1',
    setCurrentProjectId: vi.fn(),
}));

const PROJECTS = [
    { id: 'p1', name: 'Atlas', color: '#c9b8ff' },
    { id: 'p2', name: 'Beacon', color: '#80cbc4' },
];

// Two running runs, both on the active project — drives the "2 running" pill
// and the switcher's live badge.
const RUNS = [
    { id: 'r1', project_id: 'p1' },
    { id: 'r2', project_id: 'p1' },
];

function mountSidebar(props = {}) {
    return render(
        <MemoryRouter initialEntries={['/studio']}>
            <ShellDataProvider>
                <Routes>
                    <Route path="/studio" element={<AppSidebar railOpen onToggleRail={() => {}} {...props} />} />
                    <Route path="/forge/runs" element={<div>RUNS PAGE</div>} />
                </Routes>
            </ShellDataProvider>
        </MemoryRouter>,
    );
}

function mountTopbar(props = {}) {
    return render(
        <MemoryRouter initialEntries={['/studio']}>
            <ShellDataProvider>
                <Routes>
                    <Route path="/studio" element={<AppTopbar {...props} />} />
                    <Route path="/studio/project/:projectId/board" element={<div>BOARD</div>} />
                </Routes>
            </ShellDataProvider>
        </MemoryRouter>,
    );
}

beforeEach(() => {
    vi.clearAllMocks();
    api.getProjects.mockResolvedValue(PROJECTS);
    api.getNotifications.mockResolvedValue([]);
    api.forge.listAgents.mockResolvedValue([{ id: 'a1' }, { id: 'a2' }]);
    api.forge.listRuns.mockImplementation(({ status }) => Promise.resolve(status === 'running' ? RUNS : []));
});

describe('AppSidebar — collapsible rail', () => {
    it('renders the nav in the design order, with BUILD and PROJECT section headers', () => {
        mountSidebar();

        const labels = ['Home', 'Inbox', 'My Work', 'Chat', 'Agents', 'Runs', 'Conductor',
            'Agent Runtimes', 'MCP Servers', 'Overview', 'Board', 'Backlog', 'Roadmap', 'Workflow', 'Settings'];
        for (const l of labels) expect(screen.getByText(l)).toBeInTheDocument();

        expect(screen.getByText('BUILD')).toBeInTheDocument();
        expect(screen.getByText('PROJECT')).toBeInTheDocument();
    });

    it('is 248px wide and un-collapsed when railOpen is true', () => {
        const { container } = mountSidebar({ railOpen: true });

        const wrap = container.querySelector('.railwrap');
        const rail = container.querySelector('.rail');
        // `.rc` is the collapse class — absent means the 248px expanded state.
        expect(wrap.classList.contains('rc')).toBe(false);
        expect(rail.classList.contains('rc')).toBe(false);
    });

    it('collapses to the icon rail when railOpen is false', () => {
        const { container } = mountSidebar({ railOpen: false });

        // Both nodes need `.rc`: the wrap drives the 66px width, the rail drives
        // the label hiding / centring / header dividers / user-menu flyout.
        expect(container.querySelector('.railwrap').classList.contains('rc')).toBe(true);
        expect(container.querySelector('.rail').classList.contains('rc')).toBe(true);
    });

    it('gives every nav row a native tooltip so the collapsed rail stays legible', () => {
        mountSidebar({ railOpen: false });

        // The label text stays in the DOM (CSS hides `.rl`); the tooltip is what
        // identifies the row once only the icon is visible.
        expect(screen.getByTitle('Conductor')).toBeInTheDocument();
        expect(screen.getByTitle('MCP Servers')).toBeInTheDocument();
        expect(screen.getByTitle('Alex Rivera')).toBeInTheDocument();
    });

    it('wraps the labels and badges in .rl so collapsing can hide them', () => {
        const { container } = mountSidebar();
        const home = screen.getByTitle('Home');
        expect(within(home).getByText('Home').classList.contains('rl')).toBe(true);
        expect(container.querySelectorAll('.rl').length).toBeGreaterThan(0);
    });

    it('calls onToggleRail when the panel button is clicked', () => {
        const onToggleRail = vi.fn();
        mountSidebar({ onToggleRail });

        fireEvent.click(screen.getByTitle('Toggle sidebar'));
        expect(onToggleRail).toHaveBeenCalledTimes(1);
    });

    it('opens the user menu, which carries .usermenu so it can fly out when collapsed', () => {
        const { container } = mountSidebar({ railOpen: false });
        expect(container.querySelector('.usermenu')).toBeNull();

        fireEvent.click(screen.getByTitle('Alex Rivera'));

        expect(container.querySelector('.usermenu')).not.toBeNull();
        expect(screen.getByText('Sign out')).toBeInTheDocument();
    });

    it('still navigates — the rows keep their click handlers through the port', async () => {
        mountSidebar();
        fireEvent.click(screen.getByTitle('Runs'));
        expect(await screen.findByText('RUNS PAGE')).toBeInTheDocument();
    });

    it('shows the live running count on the Runs row', async () => {
        mountSidebar();
        // Two running runs come back from the shared shell query. Scope to the row —
        // the Agents row carries its own count badge.
        const runs = screen.getByTitle('Runs');
        await waitFor(() => expect(within(runs).getByText('2')).toBeInTheDocument());
    });
});

describe('AppTopbar — blended bar', () => {
    it('renders the logo lockup and the search pill', () => {
        mountTopbar();
        expect(screen.getByText('Agentira')).toBeInTheDocument();
        expect(screen.queryByText('Acme Inc')).not.toBeInTheDocument();
        expect(screen.getByText('Search or jump…')).toBeInTheDocument();
        expect(screen.getByText('⌘K')).toBeInTheDocument();
    });

    it('hosts the project switcher (moved out of the sidebar) and shows the active project', async () => {
        mountTopbar();
        expect(screen.getByText('PROJECT')).toBeInTheDocument();
        expect(await screen.findByText('Atlas')).toBeInTheDocument();
    });

    it('opens the SWITCH PROJECT dropdown and switches project on select', async () => {
        mountTopbar();

        fireEvent.click(await screen.findByText('Atlas'));
        expect(screen.getByText('SWITCH PROJECT')).toBeInTheDocument();

        fireEvent.click(screen.getByText('Beacon'));

        await waitFor(() => expect(setCurrentProjectId).toHaveBeenCalledWith('p2'));
        expect(await screen.findByText('BOARD')).toBeInTheDocument();
    });

    it('shows the pulse pill with the live running total', async () => {
        mountTopbar();
        expect(await screen.findByText('2 running')).toBeInTheDocument();
    });

    it('opens the New menu and routes "New project" to the wizard callback', async () => {
        const onNewProject = vi.fn();
        mountTopbar({ onNewProject });

        fireEvent.click(screen.getByText('New'));
        fireEvent.click(screen.getByText('New project'));

        expect(onNewProject).toHaveBeenCalledTimes(1);
    });
});
