import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { Chat } from './Chat';
import { api } from '../api';

vi.mock('../api', () => ({
    api: {
        forge: {
            listChats: vi.fn(),
            listMessages: vi.fn(),
            sendRuntimeChat: vi.fn(),
            stopChat: vi.fn(),
        },
    },
}));

// jsdom doesn't implement scrollIntoView; the pane calls it on each new turn.
window.HTMLElement.prototype.scrollIntoView = vi.fn();

const CONVOS = [
    {
        agent_id: 'a1', agent_name: 'Conductor', scope_key: 'chat:project:p1',
        label: 'Chat — Smoke', last_message: 'on it', last_used_at: '2026-06-19T00:00:02.000Z',
    },
    {
        agent_id: 'a2', agent_name: 'Implementer', scope_key: 'chat:default',
        label: 'Chat — no project', last_message: 'done', last_used_at: '2026-06-19T00:00:01.000Z',
    },
];

describe('Chat page', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.forge.listChats.mockResolvedValue(CONVOS);
        api.forge.listMessages.mockResolvedValue([]);
        api.forge.sendRuntimeChat.mockResolvedValue({});
    });

    it('lists every agent conversation from GET /forge/chats', async () => {
        render(<Chat />);
        await waitFor(() => expect(api.forge.listChats).toHaveBeenCalled());
        expect((await screen.findAllByText('Conductor')).length).toBeGreaterThan(0);
        expect(screen.getByText('Implementer')).toBeInTheDocument();
        expect(screen.getByText('on it')).toBeInTheDocument();
    });

    it('auto-selects the first conversation and loads its messages by scope_key', async () => {
        render(<Chat />);
        await waitFor(() => expect(api.forge.listMessages).toHaveBeenCalled());
        const call = api.forge.listMessages.mock.calls.find(([id]) => id === 'a1');
        expect(call).toBeTruthy();
        expect(call[1]).toMatchObject({ scope_key: 'chat:project:p1', limit: 50 });
    });

    it('switches conversation when another row is clicked', async () => {
        render(<Chat />);
        const [implRow] = await screen.findAllByText('Implementer');
        fireEvent.click(implRow);
        await waitFor(() => {
            const call = api.forge.listMessages.mock.calls.find(([id]) => id === 'a2');
            expect(call).toBeTruthy();
            expect(call[1]).toMatchObject({ scope_key: 'chat:default' });
        });
    });

    it('sends a message to the selected agent with its scope_key', async () => {
        render(<Chat />);
        await screen.findAllByText('Conductor');
        const box = await screen.findByPlaceholderText(/Type a message/i);
        fireEvent.change(box, { target: { value: 'hello' } });
        fireEvent.keyDown(box, { key: 'Enter' });
        await waitFor(() => {
            expect(api.forge.sendRuntimeChat).toHaveBeenCalledWith('a1', expect.objectContaining({
                content: 'hello', scope_key: 'chat:project:p1',
            }));
        });
    });
});
