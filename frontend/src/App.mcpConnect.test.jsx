// /mcp-connect hands an existing Agentira login to the configured MCP service and never to anything else.
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

const auth = { user: null, loading: false };
vi.mock('./context/AuthContext', () => ({ useAuth: () => auth, AuthProvider: ({ children }) => children }));
const getAuthConfig = vi.fn();
vi.mock('./api', () => ({ api: { getAuthConfig: (...a) => getAuthConfig(...a) } }));
const post = vi.fn();
vi.mock('./mcpConnect', async (orig) => ({ ...(await orig()), postToMcp: (...a) => post(...a) }));
const { McpConnect } = await import('./pages/McpConnect');

const MCP = 'http://localhost:8000';
const authorize = `${MCP}/authorize?client_id=c&redirect_uri=http%3A%2F%2Flocalhost%3A1%2Fcb&state=s`;
const at = (ret) => render(
    <MemoryRouter initialEntries={[`/mcp-connect?return=${encodeURIComponent(ret)}`]}>
        <Routes>
            <Route path="/mcp-connect" element={<McpConnect />} />
            <Route path="/login" element={<div>login page</div>} />
            <Route path="/studio" element={<div>studio home</div>} />
        </Routes>
    </MemoryRouter>,
);

describe('McpConnect', () => {
    beforeEach(() => { post.mockClear(); getAuthConfig.mockResolvedValue({ mcp_url: MCP }); auth.user = null; });

    it('logged in: posts the login to the MCP authorize URL it was sent from', async () => {
        auth.user = { name: 'ali' };
        at(authorize);
        await waitFor(() => expect(post).toHaveBeenCalled());
        expect(post.mock.calls[0][0].href).toBe(authorize);
        expect(screen.getByText(/Connecting you to Agentira/)).toBeTruthy();
    });

    it('logged out: shows the Agentira login first, no handoff', () => {
        at(authorize);
        expect(screen.getByText('login page')).toBeTruthy();
        expect(post).not.toHaveBeenCalled();
    });

    it('return address that is not the configured MCP service: goes home, never hands over the login', async () => {
        auth.user = { name: 'ali' };
        at('http://evil.test/authorize?client_id=c');
        await waitFor(() => expect(screen.getByText('studio home')).toBeTruthy());
        expect(post).not.toHaveBeenCalled();
    });

    it('MCP address not configured: goes home', async () => {
        auth.user = { name: 'ali' };
        getAuthConfig.mockResolvedValue({ mcp_url: '' });
        at(authorize);
        await waitFor(() => expect(screen.getByText('studio home')).toBeTruthy());
        expect(post).not.toHaveBeenCalled();
    });
});
