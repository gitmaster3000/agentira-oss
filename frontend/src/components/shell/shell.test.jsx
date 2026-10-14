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
        search: vi.fn(),
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
    { id: 'p1', name: 'Atlas' },
    { id: 'p2', name: 'Beacon' },
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

function mountTopbar(props = {}, entry = '/studio/project/p1/board') {
    return render(
        <MemoryRouter initialEntries={[entry]}>
            <ShellDataProvider>
                <Routes>
                    <Route path="/studio" element={<AppTopbar {...props} />} />
                    <Route path="/studio/project/:projectId/board" element={<><AppTopbar {...props} /><div>BOARD</div></>} />
                    <Route path="/studio/project/:projectId/roadmap" element={<div>ROADMAP</div>} />
                    <Route path="/forge" element={<AppTopbar isBuild {...props} />} />
                    <Route path="/forge/agents" element={<div>AGENTS PAGE</div>} />
                    <Route path="/studio/tasks/:taskId" element={<div>TASK PAGE</div>} />
                </Routes>
            </ShellDataProvider>
        </MemoryRouter>,
    );
}

// Project name appears in the switcher and the breadcrumb; wait for projects, take the switcher.
const switcher = async () => (await screen.findAllByText('Atlas'))[0];

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

        const labels = ['Agents', 'Runs', 'Conductor', 'Agent Runtimes', 'MCP Servers'];
        for (const l of labels) expect(screen.getByText(l)).toBeInTheDocument();
        // Work destinations moved to the top bar; the sidebar is Build-only.
        for (const l of ['Home', 'Inbox', 'My Work', 'Chat']) expect(screen.queryByText(l)).not.toBeInTheDocument();

        expect(screen.getByText('BUILD')).toBeInTheDocument();
    });

    it('has no PROJECTS section or project sub-nav (project switcher lives in the top bar)', async () => {
        mountSidebar();
        await screen.findByText('Runs');
        expect(screen.queryByText('PROJECT')).not.toBeInTheDocument();
        expect(screen.queryByText('PROJECTS')).not.toBeInTheDocument();
        expect(screen.queryByTitle('Atlas')).not.toBeInTheDocument();
        expect(screen.queryByText('New project')).not.toBeInTheDocument();
        for (const l of ['Overview', 'Board', 'Backlog', 'Roadmap', 'Workflow', 'Deploy']) {
            expect(screen.queryByText(l)).not.toBeInTheDocument();
        }
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
    });

    it('wraps the labels and badges in .rl so collapsing can hide them', () => {
        const { container } = mountSidebar();
        const home = screen.getByTitle('Agents');
        expect(within(home).getByText('Agents').classList.contains('rl')).toBe(true);
        expect(container.querySelectorAll('.rl').length).toBeGreaterThan(0);
    });

    it('calls onToggleRail when the panel button is clicked', () => {
        const onToggleRail = vi.fn();
        mountSidebar({ onToggleRail });

        fireEvent.click(screen.getByTitle('Toggle sidebar'));
        expect(onToggleRail).toHaveBeenCalledTimes(1);
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
        expect(screen.getByPlaceholderText('Search or jump…')).toBeInTheDocument();
        expect(screen.getByText('⌘K')).toBeInTheDocument();
    });

    it('searches as you type, groups results, and navigates on click', async () => {
        api.search.mockResolvedValue({
            tasks: [{ id: 't1', key: 'AP-1', title: 'Fix login loop', status: 'Todo', project_id: 'p2', project_name: 'Beacon' }],
            epics: [], projects: [], agents: [],
        });
        mountTopbar();
        const input = screen.getByPlaceholderText('Search or jump…');
        fireEvent.focus(input);
        fireEvent.change(input, { target: { value: 'login' } });
        await waitFor(() => expect(api.search).toHaveBeenCalledWith('login'));
        expect(await screen.findByText('TASKS')).toBeInTheDocument();
        expect(screen.getByText('AP-1 · Beacon')).toBeInTheDocument();
        fireEvent.keyDown(input, { key: 'Enter' });
        expect(await screen.findByText('TASK PAGE')).toBeInTheDocument();
    });

    it('shows a no-results message', async () => {
        api.search.mockResolvedValue({ tasks: [], epics: [], projects: [], agents: [] });
        mountTopbar();
        const input = screen.getByPlaceholderText('Search or jump…');
        fireEvent.focus(input);
        fireEvent.change(input, { target: { value: 'zzzq' } });
        expect(await screen.findByText('No matches for “zzzq”.')).toBeInTheDocument();
    });

    it('hosts the project switcher (moved out of the sidebar) and shows the active project', async () => {
        mountTopbar();
        expect(screen.getByText('PROJECT')).toBeInTheDocument();
        expect(await switcher()).toBeInTheDocument();
    });

    it('names the project in plain readable text, not a per-project colour', async () => {
        mountTopbar();
        expect((await switcher()).style.color).toBe('var(--text-primary)');
    });

    it('opens the SWITCH PROJECT dropdown and switches project on select', async () => {
        mountTopbar();

        fireEvent.click(await switcher());
        expect(screen.getByText('SWITCH PROJECT')).toBeInTheDocument();

        fireEvent.click(screen.getByText('Beacon'));

        await waitFor(() => expect(setCurrentProjectId).toHaveBeenCalledWith('p2'));
        expect(await screen.findByText('BOARD')).toBeInTheDocument();
    });

    it('does not show the N running chip in Work', async () => {
        mountTopbar();
        await switcher();
        expect(screen.queryByText(/running/)).not.toBeInTheDocument();
    });

    it('shows the pulse pill with the live running total in Build', async () => {
        mountTopbar({}, '/forge');
        expect(await screen.findByText('2 running')).toBeInTheDocument();
    });

    it('has a Work | Build switch; Build goes to /forge', async () => {
        mountTopbar();
        expect(screen.getByRole('button', { name: 'Work' })).toHaveAttribute('aria-pressed', 'true');
        fireEvent.click(screen.getByRole('button', { name: 'Build' }));
        expect(await screen.findByText('Overview')).toBeInTheDocument();
    });

    it('hides the hamburger outside Build and the project switcher outside a project', async () => {
        mountTopbar({}, '/studio');
        expect(screen.queryByLabelText('Open navigation')).not.toBeInTheDocument();
        expect(screen.queryByText('PROJECT')).not.toBeInTheDocument();
    });

    it('lists Task, Project, Epic, Milestone and Agent in the New menu', async () => {
        mountTopbar();
        await switcher();
        fireEvent.click(screen.getByText('New'));
        for (const l of ['Task', 'Project', 'Epic', 'Milestone', 'Agent']) expect(screen.getByText(l)).toBeInTheDocument();
    });

    it('New > Task inside a project fires the existing open-create-task event', async () => {
        const spy = vi.fn();
        window.addEventListener('open-create-task', spy);
        mountTopbar();
        await switcher();
        fireEvent.click(screen.getByText('New'));
        fireEvent.click(screen.getByText('Task'));
        window.removeEventListener('open-create-task', spy);
        expect(spy).toHaveBeenCalledTimes(1);
    });

    it('New > Milestone opens the roadmap', async () => {
        mountTopbar();
        await switcher();
        fireEvent.click(screen.getByText('New'));
        fireEvent.click(screen.getByText('Milestone'));
        expect(await screen.findByText('ROADMAP')).toBeInTheDocument();
    });

    it('New > Agent navigates to the agents page', async () => {
        mountTopbar();
        fireEvent.click(screen.getByText('New'));
        fireEvent.click(screen.getByText('Agent'));
        expect(await screen.findByText('AGENTS PAGE')).toBeInTheDocument();
    });

    it('avatar menu carries Inbox, My Work, Chat', () => {
        mountTopbar();
        fireEvent.click(screen.getByTitle('Alex Rivera'));
        for (const l of ['Inbox', 'My Work', 'Chat', 'Sign out']) expect(screen.getByText(l)).toBeInTheDocument();
    });

    it('opens the New menu and routes "Project" to the wizard callback', async () => {
        const onNewProject = vi.fn();
        mountTopbar({ onNewProject });
        await switcher();

        fireEvent.click(screen.getByText('New'));
        fireEvent.click(screen.getByText('Project'));

        expect(onNewProject).toHaveBeenCalledTimes(1);
    });
});
