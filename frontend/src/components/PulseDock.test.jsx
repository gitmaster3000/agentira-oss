import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { PulseDock } from './PulseDock';
import { ShellDataProvider } from './shell/shellData';
import { api } from '../api';

// PulseDock reads the shared ShellData — the SAME forge.listRuns({status:'running'})
// the top-bar pulse pill reads. The drawer is open by default (no stored pref).
vi.mock('../api', () => ({
    api: {
        getProjects: vi.fn().mockResolvedValue([]),
        getNotifications: vi.fn().mockResolvedValue([]),
        forge: {
            listRuns: vi.fn().mockResolvedValue([]),
            listAgents: vi.fn().mockResolvedValue([]),
        },
    },
}));

function renderDock() {
    return render(
        <MemoryRouter>
            <ShellDataProvider>
                <PulseDock />
            </ShellDataProvider>
        </MemoryRouter>,
    );
}

describe('PulseDock', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        // Drawer is an on-demand slide-over (default closed); open it for the test.
        vi.stubGlobal('localStorage', { getItem: () => 'true', setItem: () => {} });
        api.getProjects.mockResolvedValue([]);
        api.getNotifications.mockResolvedValue([]);
        api.forge.listAgents.mockResolvedValue([]);
        api.forge.listRuns.mockResolvedValue([]);
    });

    afterEach(() => vi.unstubAllGlobals());

    it('reads the shared forge.listRuns({status:"running"}) source', async () => {
        renderDock();
        await waitFor(() =>
            expect(api.forge.listRuns).toHaveBeenCalledWith({ status: 'running' }),
        );
    });

    it('always shows the three section headings, with empty rows when nothing is live', async () => {
        renderDock();
        expect(screen.getByText('PULSE')).toBeInTheDocument();
        // All three headings render even when empty, so it's clear what Pulse tracks.
        await waitFor(() => expect(screen.getByText('RUNNING · 0')).toBeInTheDocument());
        expect(screen.getByText('WAITING ON YOU · 0')).toBeInTheDocument();
        expect(screen.getByText('RECENT ACTIVITY')).toBeInTheDocument();
        expect(screen.getByText(/No agents running/i)).toBeInTheDocument();
    });

    it('lists the live runs under a RUNNING section', async () => {
        api.forge.listRuns.mockImplementation(({ status }) =>
            Promise.resolve(status === 'running'
                ? [
                    { id: 'r1', agent_name: 'Implementer', task_title: 'Add retry', task_key: 'ACM-1' },
                    { id: 'r2', agent_name: 'Planner', task_title: 'Spec API', task_key: 'ACM-2' },
                ]
                : []),
        );
        renderDock();
        await waitFor(() => expect(screen.getByText('RUNNING · 2')).toBeInTheDocument());
        expect(screen.getByText('Implementer')).toBeInTheDocument();
        expect(screen.getByText('Planner')).toBeInTheDocument();
    });
});
