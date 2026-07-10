import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ConnectWizard } from './ConnectWizard';
import { api } from '../../api';

vi.mock('../../api', () => ({
    api: {
        verifyDeployKey: vi.fn(),
        getDeployRepoAccess: vi.fn(),
        connectDeployProvider: vi.fn(),
    },
}));

const SERVICES = [
    { id: 'svc_1', name: 'billing-api', type: 'web service', region: 'us-west', deployable: true },
    { id: 'svc_2', name: 'billing-db', type: 'postgres', deployable: false },
];

function renderWizard(props = {}) {
    return render(
        <ConnectWizard projectId="P1" onClose={vi.fn()} onConnected={vi.fn()} {...props} />,
    );
}

async function passKeyStep() {
    fireEvent.change(screen.getByLabelText('API KEY'), { target: { value: 'rw_live_abc' } });
    fireEvent.click(screen.getByRole('button', { name: 'Verify key' }));
    await screen.findByText('Key valid');
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
}

describe('ConnectWizard', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.verifyDeployKey.mockResolvedValue({ valid: true, account: 'acme-prod', services: SERVICES });
        api.getDeployRepoAccess.mockResolvedValue({ repo: 'acme/billing-api', granted: true, install_url: 'https://github.com/apps/x' });
        api.connectDeployProvider.mockResolvedValue({ provider: 'railway', repo: 'acme/billing-api' });
    });

    it('masks the key by default and never echoes it back', async () => {
        renderWizard();
        const input = screen.getByLabelText('API KEY');
        expect(input).toHaveAttribute('type', 'password');
        fireEvent.click(screen.getByRole('button', { name: 'Show key' }));
        expect(input).toHaveAttribute('type', 'text');
    });

    it('probes the key once and reports the account on success', async () => {
        renderWizard();
        fireEvent.change(screen.getByLabelText('API KEY'), { target: { value: 'rw_live_abc' } });
        fireEvent.click(screen.getByRole('button', { name: 'Verify key' }));

        expect(await screen.findByText('Key valid')).toBeInTheDocument();
        expect(screen.getByText('acme-prod')).toBeInTheDocument();
        expect(api.verifyDeployKey).toHaveBeenCalledWith('P1', 'railway', 'rw_live_abc');
        expect(api.verifyDeployKey).toHaveBeenCalledTimes(1);
    });

    it('surfaces the cause and the fix when the key is rejected', async () => {
        api.verifyDeployKey.mockResolvedValue({
            valid: false,
            error: { headline: 'Railway rejected this key (401)', detail: 'It may be expired or revoked.' },
        });
        renderWizard();
        fireEvent.change(screen.getByLabelText('API KEY'), { target: { value: 'bad' } });
        fireEvent.click(screen.getByRole('button', { name: 'Verify key' }));

        expect(await screen.findByText('Railway rejected this key (401)')).toBeInTheDocument();
        expect(screen.getByText(/It may be expired or revoked/)).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
    });

    it('blocks Continue on the repo step until access is granted', async () => {
        api.getDeployRepoAccess.mockResolvedValue({ repo: 'acme/billing-api', granted: false, install_url: 'https://github.com/apps/x' });
        renderWizard();
        await passKeyStep();

        expect(await screen.findByText('NEEDS ACCESS')).toBeInTheDocument();
        expect(screen.getByRole('link', { name: /Grant on GitHub/ })).toHaveAttribute('href', 'https://github.com/apps/x');
        expect(screen.queryByRole('button', { name: 'Continue' })).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Waiting…' })).toBeInTheDocument();
    });

    it('will not let a non-deployable service be picked, and connects with the chosen one', async () => {
        const onConnected = vi.fn();
        renderWizard({ onConnected });
        await passKeyStep();

        await screen.findByText('GRANTED');
        fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

        const db = await screen.findByRole('button', { name: /billing-db/ });
        expect(db).toBeDisabled();

        fireEvent.click(screen.getByRole('button', { name: /billing-api/ }));
        fireEvent.click(screen.getByRole('button', { name: 'Connect' }));

        await waitFor(() => expect(api.connectDeployProvider).toHaveBeenCalledWith('P1', {
            provider: 'railway', api_key: 'rw_live_abc', repo: 'acme/billing-api', service_id: 'svc_1',
        }));
        expect(onConnected).toHaveBeenCalled();
    });
});
