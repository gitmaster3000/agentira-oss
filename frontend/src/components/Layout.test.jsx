import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { Layout } from './Layout';
import { api } from '../api';

vi.mock('../api', () => ({
    api: {
        getProjects: vi.fn(),
        getNotifications: vi.fn(),
        search: vi.fn(),
        markNotificationRead: vi.fn(),
        forge: { listAgents: vi.fn(), listRuns: vi.fn() },
    },
}));
vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ user: { display_name: 'Alex' } }) }));
vi.mock('../currentProject', () => ({ useCurrentProjectId: () => 'p1', setCurrentProjectId: vi.fn() }));
vi.mock('./CreateProjectWizard', () => ({ CreateProjectWizard: () => null }));
vi.mock('./FloatingChat', () => ({ FloatingChat: () => null }));
vi.mock('./PulseDock', () => ({ PulseDock: () => null }));

function mount(path) {
    return render(
        <MemoryRouter initialEntries={[path]}>
            <Routes>
                <Route element={<Layout />}>
                    <Route path="/studio" element={<div>WORK PAGE</div>} />
                    <Route path="/forge/runs" element={<div>RUNS PAGE</div>} />
                    <Route path="/studio/project/:id/board" element={<div>BOARD PAGE</div>} />
                    <Route path="/studio/tasks/:id" element={<div>TASK PAGE</div>} />
                    <Route path="/studio/settings" element={<div>SETTINGS PAGE</div>} />
                    <Route path="/chat" element={<div>CHAT PAGE</div>} />
                    <Route path="/forge/runs/:id" element={<div>RUN PAGE</div>} />
                </Route>
            </Routes>
        </MemoryRouter>,
    );
}

beforeEach(() => {
    api.getProjects.mockResolvedValue([{ id: 'p1', name: 'Atlas' }]);
    api.getNotifications.mockResolvedValue([]);
    api.forge.listAgents.mockResolvedValue([]);
    api.forge.listRuns.mockResolvedValue([]);
});

describe('Layout — Work | Build', () => {
    it('Work renders full width with no sidebar', async () => {
        const { container } = mount('/studio');
        expect(await screen.findByText('WORK PAGE')).toBeInTheDocument();
        expect(container.querySelector('.railwrap')).toBeNull();
    });

    it('Build renders its own sidebar', async () => {
        const { container } = mount('/forge/runs');
        expect(await screen.findByText('RUNS PAGE')).toBeInTheDocument();
        expect(container.querySelector('.railwrap')).not.toBeNull();
        expect(screen.getByTitle('MCP Servers')).toBeInTheDocument();
    });

    // AP-693: one identical top bar on every authenticated route.
    it.each([
        ['/studio', 'WORK PAGE', 'Work'],
        ['/studio/project/p1/board', 'BOARD PAGE', 'Work'],
        ['/studio/tasks/t1', 'TASK PAGE', 'Work'],
        ['/studio/settings', 'SETTINGS PAGE', 'Work'],
        ['/chat', 'CHAT PAGE', 'Work'],
        ['/forge/runs', 'RUNS PAGE', 'Build'],
        ['/forge/runs/r1', 'RUN PAGE', 'Build'],
    ])('%s renders the full top bar with %s side active', async (path, page, side) => {
        const { container } = mount(path);
        expect(await screen.findByText(page)).toBeInTheDocument();
        const bars = container.querySelectorAll('header.shell-topbar');
        expect(bars).toHaveLength(1);
        const bar = within(bars[0]);
        expect(bar.getByText('Agentira')).toBeInTheDocument();
        expect(bar.getByRole('textbox', { name: 'Search' })).toBeInTheDocument();
        expect(bar.getByText('New')).toBeInTheDocument();
        expect(bar.getByRole('button', { name: /Switch to (light|dark) mode/ })).toBeInTheDocument();
        expect(bar.getByTitle('Alex')).toBeInTheDocument();
        const group = bar.getByRole('group', { name: 'Area' });
        const pressed = within(group).getAllByRole('button').filter((b) => b.getAttribute('aria-pressed') === 'true');
        expect(pressed.map((b) => b.textContent)).toEqual([side]);
    });
});
