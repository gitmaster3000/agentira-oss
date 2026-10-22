// AP-722: /sso hands an existing Agentira login to a configured connected app (Ezine) and lands on `return`.
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

const auth = { user: null, loading: false };
vi.mock('./context/AuthContext', () => ({ useAuth: () => auth, AuthProvider: ({ children }) => children }));
const open = vi.fn();
vi.mock('./connectedApps', async (orig) => {
    const real = await orig();
    const apps = [{ key: 'ezine', name: 'Ezine', url: 'http://localhost:4400' }];
    return { ...real, appForUrl: (u) => real.appForUrl(u, apps), openConnectedApp: (...a) => open(...a) };
});
const { SsoRedirect } = await import('./App');

const at = (url) => render(
    <MemoryRouter initialEntries={[url]}>
        <Routes>
            <Route path="/sso" element={<SsoRedirect />} />
            <Route path="/login" element={<div>login page</div>} />
            <Route path="/studio" element={<div>studio home</div>} />
        </Routes>
    </MemoryRouter>,
);
const sso = (ret) => `/sso?return=${encodeURIComponent(ret)}`;

describe('SsoRedirect', () => {
    beforeEach(() => { open.mockClear(); auth.user = null; });

    it('logged in: hands the login to the app and returns to the requested page', () => {
        auth.user = { name: 'ali' };
        at(sso('http://localhost:4400/?doc=d1#f'));
        expect(open).toHaveBeenCalledWith(expect.objectContaining({ key: 'ezine' }), { returnTo: '/?doc=d1#f', target: '_self' });
        expect(screen.getByText(/Signing you in to Ezine/)).toBeTruthy();
    });

    it('logged out: shows the Agentira login first, no handoff', () => {
        at(sso('http://localhost:4400/'));
        expect(screen.getByText('login page')).toBeTruthy();
        expect(open).not.toHaveBeenCalled();
    });

    it('unlisted return address: goes home, never hands over the login', () => {
        auth.user = { name: 'ali' };
        at(sso('http://evil.test/'));
        expect(screen.getByText('studio home')).toBeTruthy();
        expect(open).not.toHaveBeenCalled();
    });
});
