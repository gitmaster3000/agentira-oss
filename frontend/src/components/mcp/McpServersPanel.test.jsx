import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../../api', () => ({
    api: { forge: {
        listMcpRegistry: vi.fn(), addMcpServer: vi.fn(), updateMcpServer: vi.fn(),
        testMcpServer: vi.fn(), deleteMcpServer: vi.fn(),
        listMcpHost: vi.fn(), listAgents: vi.fn(), updateAgent: vi.fn(),
    } },
}));
import { api } from '../../api';
import { McpServersPanel } from './McpServersPanel';

const ezine = {
    id: 's1', name: 'ezine', description: '', url: 'https://e.test/mcp', auth_mode: 'agent_key',
    has_token: false, enabled: true, status: 'ok', status_detail: null, checked_at: null,
    tools: [{ name: 'get_prototype', description: 'Read a prototype', read_only: true }],
};

describe('McpServersPanel', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.forge.listMcpHost.mockResolvedValue({ checked: true, servers: [] });
        api.forge.listAgents.mockResolvedValue([]);
    });

    it('shows connection status and tools', async () => {
        api.forge.listMcpRegistry.mockResolvedValue([ezine]);
        render(<McpServersPanel ezineUrl="https://e.test/mcp" />);
        expect(await screen.findByText('Connected · 1 tools')).toBeTruthy();
        fireEvent.click(screen.getByText('Show tools'));
        expect(screen.getByText('get_prototype')).toBeTruthy();
    });

    it('Add Ezine prefills the form and connects', async () => {
        api.forge.listMcpRegistry.mockResolvedValue([]);
        api.forge.addMcpServer.mockResolvedValue(ezine);
        render(<McpServersPanel ezineUrl="https://e.test/mcp" />);
        fireEvent.click(await screen.findByText('Add Ezine'));
        fireEvent.click(screen.getByText('Connect & find tools'));
        await waitFor(() => expect(api.forge.addMcpServer).toHaveBeenCalledWith(
            expect.objectContaining({ name: 'ezine', url: 'https://e.test/mcp', auth_mode: 'agent_key' })));
        expect(await screen.findByText('Connected · 1 tools')).toBeTruthy();
    });

    it('shows the server error when connecting fails', async () => {
        api.forge.listMcpRegistry.mockResolvedValue([]);
        api.forge.addMcpServer.mockRejectedValue(new Error('Name must be 2-40 characters'));
        render(<McpServersPanel ezineUrl="x" />);
        fireEvent.click(await screen.findByText('Add Ezine'));
        fireEvent.click(screen.getByText('Connect & find tools'));
        expect(await screen.findByText('Name must be 2-40 characters')).toBeTruthy();
    });

    it('lists servers from this machine, checked by the daemon', async () => {
        api.forge.listMcpRegistry.mockResolvedValue([]);
        api.forge.listMcpHost.mockResolvedValue({ checked: true, servers: [
            { name: 'linear', transport: 'http', url: 'https://l/mcp', command: '', ok: true, tools: [{ name: 'a' }], error: '' },
            { name: 'memory', transport: 'stdio', url: '', command: 'npx', ok: null, tools: [], error: '' },
        ] });
        render(<McpServersPanel ezineUrl="x" />);
        expect(await screen.findByText('linear')).toBeTruthy();
        expect(screen.getByText('Connected · 1 tools')).toBeTruthy();
        expect(screen.getByText('Runs on your machine')).toBeTruthy();
    });

    it('says so when no daemon could check this machine', async () => {
        api.forge.listMcpRegistry.mockResolvedValue([]);
        api.forge.listMcpHost.mockResolvedValue({ checked: false, servers: [] });
        render(<McpServersPanel ezineUrl="x" />);
        expect(await screen.findByText(/No daemon is online/)).toBeTruthy();
    });

    it('warns when a connected server shares a name with one on this machine', async () => {
        api.forge.listMcpRegistry.mockResolvedValue([ezine]);
        api.forge.listMcpHost.mockResolvedValue({ checked: true, servers: [
            { name: 'ezine', transport: 'http', url: 'https://other/mcp', command: '', ok: true, tools: [], error: '' }] });
        render(<McpServersPanel ezineUrl="x" />);
        expect(await screen.findByText(/same name as a server on this machine/)).toBeTruthy();
    });

    it('switches a server on and off per agent', async () => {
        api.forge.listMcpRegistry.mockResolvedValue([ezine]);
        api.forge.listAgents.mockResolvedValue([
            { id: 'a1', name: 'implementer-1', mcp_servers: [], mcp_tool_allow: {} },
            { id: 'a2', name: 'reviewer', mcp_servers: ['ezine'], mcp_tool_allow: {} }]);
        api.forge.updateAgent.mockResolvedValue({});
        render(<McpServersPanel ezineUrl="x" />);
        const on = await screen.findByLabelText('implementer-1 can use ezine');
        const off = screen.getByLabelText('reviewer can use ezine');
        expect(off.checked).toBe(true);
        fireEvent.click(on);
        await waitFor(() => expect(api.forge.updateAgent).toHaveBeenCalledWith('a1', {
            mcp_servers: ['ezine'], mcp_tool_allow: { ezine: ['get_prototype'] } }));
        fireEvent.click(off);
        await waitFor(() => expect(api.forge.updateAgent).toHaveBeenCalledWith('a2', { mcp_servers: [] }));
    });
});
