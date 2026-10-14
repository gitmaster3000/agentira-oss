import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
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
});
