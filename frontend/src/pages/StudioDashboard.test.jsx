import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { StudioDashboard } from './StudioDashboard';
import { ShellDataProvider } from '../components/shell/shellData';
import { api } from '../api';

// The Home cockpit reads the shared ShellData (getProjects · forge.listRuns ·
// getNotifications) — the same single source the shell chrome uses.
vi.mock('../api', () => ({
    api: {
        getProjects: vi.fn().mockResolvedValue([]),
        getNotifications: vi.fn().mockResolvedValue([]),
        forge: {
            listRuns: vi.fn().mockResolvedValue([]),
            listAgents: vi.fn().mockResolvedValue([]),
            dismissRun: vi.fn().mockResolvedValue({ ok: true }),
        },
    },
}));

vi.mock('../context/AuthContext', () => ({
    useAuth: () => ({ user: { display_name: 'Alex Rivera' } }),
}));

function renderHome() {
    return render(
        <MemoryRouter>
            <ShellDataProvider>
                <StudioDashboard />
            </ShellDataProvider>
        </MemoryRouter>,
    );
}

describe('StudioDashboard (Home cockpit)', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.getProjects.mockResolvedValue([]);
        api.getNotifications.mockResolvedValue([]);
        api.forge.listAgents.mockResolvedValue([]);
        api.forge.listRuns.mockResolvedValue([]);
    });

    it('greets the user by first name and shows all four sections', async () => {
        renderHome();
        expect(screen.getByText(/, Alex$/)).toBeInTheDocument();
        expect(screen.getByText('LIVE NOW')).toBeInTheDocument();
        expect(screen.getByText('NEEDS YOU')).toBeInTheDocument();
        expect(screen.getByText('YOUR PROJECTS')).toBeInTheDocument();
        expect(screen.getByText('RECENT ACTIVITY')).toBeInTheDocument();
        // Empty states render when nothing is live.
        await waitFor(() => expect(screen.getByText('No agents running right now.')).toBeInTheDocument());
        expect(screen.getByText('Nothing needs you right now.')).toBeInTheDocument();
    });

    it('lists running runs under LIVE NOW and waiting runs under NEEDS YOU', async () => {
        api.forge.listRuns.mockImplementation(({ status, outcome }) =>
            Promise.resolve(
                status === 'running'
                    ? [{ id: 'r1', agent_name: 'Implementer', task_title: 'Add retry', task_key: 'ACM-1', project_id: 'p1' }]
                    : outcome === 'needs_input'
                        ? [{ id: 'r9', agent_name: 'Reviewer', task_title: 'Approve PR', task_key: 'ACM-2' }]
                        : [],
            ),
        );
        renderHome();
        await waitFor(() => expect(screen.getByText('Implementer')).toBeInTheDocument());
        expect(screen.getByText('Add retry')).toBeInTheDocument();
        expect(screen.getByText('Question from Reviewer')).toBeInTheDocument();
    });

    it('dismisses a NEEDS YOU question in one click', async () => {
        api.forge.listRuns.mockImplementation(({ outcome }) =>
            Promise.resolve(outcome === 'needs_input'
                ? [{ id: 'r9', agent_name: 'Reviewer', task_title: 'Approve PR', task_key: 'ACM-2' }]
                : []),
        );
        renderHome();
        await waitFor(() => expect(screen.getByText('Question from Reviewer')).toBeInTheDocument());
        fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
        expect(api.forge.dismissRun).toHaveBeenCalledWith('r9');
        await waitFor(() => expect(screen.queryByText('Question from Reviewer')).not.toBeInTheDocument());
        expect(screen.getByText('Nothing needs you right now.')).toBeInTheDocument();
    });

    it('renders project cards with a per-project running pill', async () => {
        api.getProjects.mockResolvedValue([
            { id: 'p1', name: 'Acme Web', key_prefix: 'ACM', task_count: 12 },
        ]);
        api.forge.listRuns.mockImplementation(({ status }) =>
            Promise.resolve(status === 'running' ? [{ id: 'r1', agent_name: 'A', project_id: 'p1' }] : []),
        );
        renderHome();
        // "Acme Web" shows on the project card and on the running run's project
        // label, so assert via the card-only details.
        await waitFor(() => expect(screen.getByText('12 tasks')).toBeInTheDocument());
        expect(screen.getAllByText('Acme Web').length).toBeGreaterThan(0);
        expect(screen.getByText('1 running')).toBeInTheDocument();
    });
});
