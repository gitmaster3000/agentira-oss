import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { McpAuthorize } from './McpAuthorize';
import { api } from '../api';
import { useAuth } from '../context/AuthContext';

vi.mock('../api', () => ({ api: { getMcpClient: vi.fn(), mcpAuthorize: vi.fn() } }));
vi.mock('../context/AuthContext', () => ({ useAuth: vi.fn() }));

const URL_ = '/mcp-authorize?client_id=c1&redirect_uri=http://localhost:1/cb&state=s&code_challenge=ch&code_challenge_method=S256&scope=agentira:read';
const renderPage = () => render(<MemoryRouter initialEntries={[URL_]}><McpAuthorize /></MemoryRouter>);

describe('McpAuthorize', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        useAuth.mockReturnValue({ user: { name: 'ali' }, loading: false });
        api.getMcpClient.mockResolvedValue({ client_name: 'Claude' });
        delete window.location;
        window.location = { assign: vi.fn() };
    });

    it('sends read-only scope by default and redirects to the client', async () => {
        api.mcpAuthorize.mockResolvedValue({ redirect_url: 'http://localhost:1/cb?code=X' });
        renderPage();
        await screen.findByText(/Connect Claude/);
        fireEvent.click(screen.getByText('Allow'));
        await waitFor(() => expect(window.location.assign).toHaveBeenCalledWith('http://localhost:1/cb?code=X'));
        expect(api.mcpAuthorize).toHaveBeenCalledWith(expect.objectContaining({
            approve: true, client_id: 'c1', scope: 'agentira:read', code_challenge: 'ch', state: 's',
        }));
    });

    it('requests write scope when the user allows changes', async () => {
        api.mcpAuthorize.mockResolvedValue({ redirect_url: 'x' });
        renderPage();
        await screen.findByText(/Connect Claude/);
        fireEvent.click(screen.getByLabelText(/Create and change/));
        fireEvent.click(screen.getByText('Allow'));
        await waitFor(() => expect(api.mcpAuthorize).toHaveBeenCalledWith(
            expect.objectContaining({ scope: 'agentira:read agentira:write' })));
    });

    it('Cancel sends approve=false', async () => {
        api.mcpAuthorize.mockResolvedValue({ redirect_url: 'x' });
        renderPage();
        await screen.findByText(/Connect Claude/);
        fireEvent.click(screen.getByText('Cancel'));
        await waitFor(() => expect(api.mcpAuthorize).toHaveBeenCalledWith(expect.objectContaining({ approve: false })));
    });
});
