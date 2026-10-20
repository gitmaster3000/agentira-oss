import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../../api', () => ({
    api: { forge: {
        listMcpRegistry: vi.fn(), addMcpServer: vi.fn(), updateMcpServer: vi.fn(),
        testMcpServer: vi.fn(), deleteMcpServer: vi.fn(),
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
    beforeEach(() => vi.clearAllMocks());

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
});
