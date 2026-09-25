import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { CliAuth } from './CliAuth';
import { api } from '../api';
import { useAuth } from '../context/AuthContext';

vi.mock('../api', () => ({
    api: { getAuthConfig: vi.fn(), approveCliLogin: vi.fn(), googleAuth: vi.fn() },
}));
vi.mock('../context/AuthContext', () => ({ useAuth: vi.fn() }));

const renderAt = (url) => render(<MemoryRouter initialEntries={[url]}><CliAuth /></MemoryRouter>);

describe('CliAuth page', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.approveCliLogin.mockResolvedValue({ ok: true });
    });

    it('keeps the same input element while typing (no remount per keystroke)', async () => {
        useAuth.mockReturnValue({ user: null, loading: false, login: vi.fn() });
        api.getAuthConfig.mockResolvedValue({ google: false, github: false, dev: false });
        renderAt('/cli-auth?user_code=ABCD');
        const pw = screen.getByPlaceholderText('Password');
        fireEvent.change(pw, { target: { value: 's' } });
        fireEvent.change(screen.getByPlaceholderText('Password'), { target: { value: 'se' } });
        expect(screen.getByPlaceholderText('Password')).toBe(pw);
        expect(pw.value).toBe('se');
    });

    it('dev mode auto-approves for a signed-in admin', async () => {
        useAuth.mockReturnValue({ user: { name: 'admin', role: 'admin' }, loading: false, logout: vi.fn() });
        api.getAuthConfig.mockResolvedValue({ dev: true });
        renderAt('/cli-auth?user_code=ABCD');
        await waitFor(() => expect(api.approveCliLogin).toHaveBeenCalledWith('ABCD'));
        expect(await screen.findByText(/Daemon authorized/)).toBeTruthy();
    });

    it('prod mode waits for the click', async () => {
        useAuth.mockReturnValue({ user: { name: 'admin', role: 'admin' }, loading: false, logout: vi.fn() });
        api.getAuthConfig.mockResolvedValue({ dev: false });
        renderAt('/cli-auth?user_code=ABCD');
        await waitFor(() => expect(api.getAuthConfig).toHaveBeenCalled());
        expect(api.approveCliLogin).not.toHaveBeenCalled();
    });
});
