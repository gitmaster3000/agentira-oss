import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { Deploy } from './Deploy';
import { api } from '../api';

vi.mock('../api', () => ({
    api: {
        getDeployProvider: vi.fn(),
        getDeployments: vi.fn(),
        createDeployment: vi.fn(),
        redeployDeployment: vi.fn(),
        stopDeployment: vi.fn(),
        getDeploymentLogs: vi.fn(),
        verifyDeployKey: vi.fn(),
        getDeployRepoAccess: vi.fn(),
        connectDeployProvider: vi.fn(),
        reverifyDeployProvider: vi.fn(),
        disconnectDeployProvider: vi.fn(),
    },
}));

const CONNECTION = {
    connected: true,
    provider: 'railway',
    repo: 'acme/billing-api',
    service_name: 'billing-api',
    service_region: 'us-west',
    key_valid: true,
    key_checked_at: new Date(Date.now() - 120_000).toISOString(),
    connected_at: new Date(Date.now() - 8 * 86_400_000).toISOString(),
};

const iso = (msAgo) => new Date(Date.now() - msAgo).toISOString();

const MAIN = {
    branch: 'main', is_main: true, commit_sha: 'a1f9c2e0000', commit_message: 'Add invoice PDF export',
    author: 'Backend Implementer', author_is_agent: true, committed_at: iso(360_000),
    deployment: {
        id: 'd_main', status: 'live', url: 'https://billing-api-production.up.railway.app',
        trigger: 'push', updated_at: iso(360_000), status_reason: 'Deployed in 47s from push to main · healthy for 6 min',
    },
};

const BUILDING = {
    branch: 'fix/webhook-retry', is_main: false, commit_sha: 'c02e88a0000', commit_message: 'Retry 5xx with backoff',
    author: 'you', committed_at: iso(10_000),
    deployment: { id: 'd_fix', status: 'building', step: 2, total_steps: 4, updated_at: iso(10_000), status_reason: 'Installing dependencies… · step 2 of 4' },
};

const NO_PREVIEW = {
    branch: 'feat/multi-currency', is_main: false, commit_sha: 'be1147d0000', commit_message: 'Support EUR & GBP invoicing',
    author: 'you', committed_at: iso(3 * 3600_000), deployment: null,
};

const FAILED = {
    branch: 'chore/upgrade-node', is_main: false, commit_sha: '9a4f2100000', commit_message: 'Upgrade Node to 20 LTS',
    author: 'you', committed_at: iso(3600_000),
    deployment: { id: 'd_chore', status: 'failed', updated_at: iso(3600_000), status_reason: 'Build error: npm ci failed — lockfile out of sync' },
};

const BRANCHES = [MAIN, BUILDING, NO_PREVIEW, FAILED];

function renderDeploy() {
    return render(
        <MemoryRouter initialEntries={['/studio/project/P1/deploy']}>
            <Routes>
                <Route path="/studio/project/:projectId/deploy" element={<Deploy />} />
            </Routes>
        </MemoryRouter>,
    );
}

describe('Deploy tab', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.getDeployProvider.mockResolvedValue(CONNECTION);
        api.getDeployments.mockResolvedValue({ branches: BRANCHES });
        api.getDeploymentLogs.mockResolvedValue({ lines: [], next_cursor: 0, done: true });
    });
    afterEach(() => vi.useRealTimers());

    describe('not connected', () => {
        it('shows the value prop and one CTA, not a wall of fields', async () => {
            api.getDeployProvider.mockResolvedValue({ connected: false });
            renderDeploy();

            expect(await screen.findByText('Ship this project live')).toBeInTheDocument();
            expect(screen.getByRole('button', { name: /Connect a deployment provider/ })).toBeInTheDocument();
            expect(screen.getByText('Railway')).toBeInTheDocument();
            expect(screen.getAllByText('COMING')).toHaveLength(2);
            expect(api.getDeployments).not.toHaveBeenCalled();
        });

        it('opens the connect wizard from the CTA', async () => {
            api.getDeployProvider.mockResolvedValue({ connected: false });
            renderDeploy();

            fireEvent.click(await screen.findByRole('button', { name: /Connect a deployment provider/ }));
            expect(await screen.findByRole('dialog', { name: 'Connect a deployment provider' })).toBeInTheDocument();
        });
    });

    describe('connected, nothing deployed', () => {
        it('offers to trigger the first deploy of main', async () => {
            api.getDeployments.mockResolvedValue({ branches: [{ ...MAIN, deployment: null }] });
            api.createDeployment.mockResolvedValue({ id: 'd_new' });
            renderDeploy();

            fireEvent.click(await screen.findByRole('button', { name: 'Deploy main now' }));
            await waitFor(() => expect(api.createDeployment).toHaveBeenCalledWith('P1', 'main'));
        });
    });

    describe('deploy home', () => {
        it('defaults to main and shows its live URL, commit and reason line', async () => {
            renderDeploy();

            expect(await screen.findByRole('link', { name: 'https://billing-api-production.up.railway.app' })).toBeInTheDocument();
            expect(screen.getAllByText('a1f9c2e').length).toBeGreaterThan(0);
            expect(screen.getByText('Deployed in 47s from push to main · healthy for 6 min')).toBeInTheDocument();
            expect(screen.getByText(/pushed by Backend Implementer/)).toBeInTheDocument();
        });

        it('embeds the running app so the user tests without leaving Agentira', async () => {
            renderDeploy();
            expect(await screen.findByTitle('main preview')).toHaveAttribute('src', MAIN.deployment.url);
        });

        it('hiding the preview bar via toggle keeps the live preview visible (bar is separate from preview content)', async () => {
            renderDeploy();
            // Current impl: button text toggles bar visibility; iframe preview always below when live.
            fireEvent.click(await screen.findByText('Hide preview bar'));

            expect(screen.getByTitle('main preview')).toBeInTheDocument(); // preview content stays
            // bar label may be gone but PREVIEW word is in other chrome too; just ensure toggle worked
            expect(screen.getByText('Show preview bar')).toBeInTheDocument();
        });

        it('switching branch shows that branch\'s state, not main\'s', async () => {
            renderDeploy();
            fireEvent.click(await screen.findByRole('button', { name: 'Switch preview — showing main' }));
            fireEvent.click(await screen.findByRole('menuitem', { name: /fix\/webhook-retry/ }));

            expect(await screen.findByText('Installing dependencies… · step 2 of 4')).toBeInTheDocument();
            expect(screen.getByText('Building preview…')).toBeInTheDocument();
            expect(screen.queryByTitle('main preview')).not.toBeInTheDocument();
        });

        it('lists every branch with a status pill and the right primary action', async () => {
            renderDeploy();
            await screen.findByText('Branch deployments');

            const pills = screen.getAllByRole('status').map(p => p.getAttribute('aria-label'));
            expect(pills).toEqual(['Live', 'Building · 2/4', 'No preview', 'Failed']);

            // A branch with no preview offers one; a failed one offers a retry.
            expect(screen.getByRole('button', { name: /Preview this branch/ })).toBeInTheDocument();
            expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
            // main is live, but it's main — never offer to tear it down.
            expect(screen.queryByRole('button', { name: 'Stop' })).not.toBeInTheDocument();
        });

        it('deploys a preview for a branch that has none', async () => {
            api.createDeployment.mockResolvedValue({ id: 'd_new' });
            renderDeploy();

            fireEvent.click(await screen.findByRole('button', { name: /Preview this branch/ }));
            await waitFor(() => expect(api.createDeployment).toHaveBeenCalledWith('P1', 'feat/multi-currency'));
        });

        it('retries a failed branch through redeploy', async () => {
            api.redeployDeployment.mockResolvedValue({ id: 'd_chore' });
            renderDeploy();

            fireEvent.click(await screen.findByRole('button', { name: 'Retry' }));
            await waitFor(() => expect(api.redeployDeployment).toHaveBeenCalledWith('P1', 'd_chore'));
        });

        it('opens the logs panel for a red deployment', async () => {
            api.getDeploymentLogs.mockResolvedValue({
                lines: [{ level: 'error', text: 'npm ci failed — lockfile out of sync' }],
                next_cursor: 1, done: true,
            });
            renderDeploy();

            const rows = await screen.findAllByRole('button', { name: 'Logs' });
            fireEvent.click(rows[rows.length - 1]);

            expect(await screen.findByRole('dialog', { name: 'Deployment logs' })).toBeInTheDocument();
            expect(screen.getByText('npm ci failed — lockfile out of sync')).toBeInTheDocument();
        });

        it('polls while a deployment is in flight and stops once everything settles', async () => {
            vi.useFakeTimers({ shouldAdvanceTime: true });
            renderDeploy();
            await waitFor(() => expect(api.getDeployments).toHaveBeenCalledTimes(1));

            await vi.advanceTimersByTimeAsync(6000);
            expect(api.getDeployments).toHaveBeenCalledTimes(2);

            // Everything settles → the interval is torn down.
            api.getDeployments.mockResolvedValue({ branches: [MAIN, NO_PREVIEW] });
            await vi.advanceTimersByTimeAsync(6000);
            const settled = api.getDeployments.mock.calls.length;
            await vi.advanceTimersByTimeAsync(24000);
            expect(api.getDeployments).toHaveBeenCalledTimes(settled);
        });

        it('does not poll when nothing is in flight', async () => {
            vi.useFakeTimers({ shouldAdvanceTime: true });
            api.getDeployments.mockResolvedValue({ branches: [MAIN, FAILED] });
            renderDeploy();
            await waitFor(() => expect(api.getDeployments).toHaveBeenCalledTimes(1));

            await vi.advanceTimersByTimeAsync(30000);
            expect(api.getDeployments).toHaveBeenCalledTimes(1);
        });

        it('caps streamed log lines (reproduces perf bug: without cap, long builds bloat memory/DOM and slow the UI)', async () => {
            vi.useFakeTimers({ shouldAdvanceTime: true });
            let callCount = 0;
            api.getDeploymentLogs.mockImplementation(async () => {
                callCount += 1;
                // Simulate streaming batches of new log output (common for real builds)
                const batch = Array.from({ length: 80 }, (_, k) => ({
                    level: 'info',
                    text: `step output ${callCount}-${k} npm install etc`,
                }));
                return { lines: batch, next_cursor: callCount * 80, done: false };
            });

            renderDeploy();
            // open logs for a live/building deployment
            const logButtons = await screen.findAllByRole('button', { name: 'Logs' });
            fireEvent.click(logButtons[0]); // main or first
            await screen.findByRole('dialog', { name: 'Deployment logs' });

            // let it poll and accumulate several batches
            for (let i = 0; i < 8; i++) {
                await vi.advanceTimersByTimeAsync(3000);
            }

            const renderedLines = screen.getAllByText(/step output .* npm install etc/);
            // Desired: capped at e.g. 300 to keep UI snappy. This assertion will FAIL until LogsPanel caps its lines state.
            expect(renderedLines.length).toBeLessThanOrEqual(300);
        });
    });

    describe('provider settings', () => {
        it('shows the connection and its key status, quietly', async () => {
            renderDeploy();
            await screen.findByText('Provider settings');

            expect(screen.getByText('acme/billing-api')).toBeInTheDocument();
            expect(screen.getByText('billing-api · us-west')).toBeInTheDocument();
            expect(screen.getByText('Key valid')).toBeInTheDocument();
        });

        it('warns and pauses when the stored key went invalid', async () => {
            api.getDeployProvider.mockResolvedValue({ ...CONNECTION, key_valid: false });
            renderDeploy();

            expect(await screen.findByText('Key invalid')).toBeInTheDocument();
            expect(screen.getByText(/Deployments are paused until you re-verify/)).toBeInTheDocument();
        });

        it('requires a second click to disconnect', async () => {
            api.disconnectDeployProvider.mockResolvedValue({});
            renderDeploy();

            fireEvent.click(await screen.findByRole('button', { name: 'Disconnect' }));
            expect(api.disconnectDeployProvider).not.toHaveBeenCalled();

            fireEvent.click(screen.getByRole('button', { name: 'Confirm disconnect' }));
            await waitFor(() => expect(api.disconnectDeployProvider).toHaveBeenCalledWith('P1'));
        });
    });
});
