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

    it('shows one row per agent, not one per conversation', async () => {
        // Same agent (a1) with two scopes + a second agent (a2): the left rail
        // must collapse to two agent rows, not three conversation rows.
        api.forge.listChats.mockResolvedValue([
            { agent_id: 'a1', agent_name: 'Conductor', scope_key: 'chat:project:p1',
              label: 'About Smoke', last_message: 'on it', last_used_at: '2026-06-19T00:00:03.000Z' },
            { agent_id: 'a1', agent_name: 'Conductor', scope_key: 'chat:default',
              label: 'General', last_message: 'hi', last_used_at: '2026-06-19T00:00:02.000Z' },
            { agent_id: 'a2', agent_name: 'Implementer', scope_key: 'chat:default',
              label: 'General', last_message: 'done', last_used_at: '2026-06-19T00:00:01.000Z' },
        ]);
        render(<Chat />);
        // Header shows the distinct-agent count, and Conductor renders once on
        // the rail with a "2 conversations" hint.
        await waitFor(() => expect(screen.getByText('2 agents')).toBeInTheDocument());
        expect(screen.getByText('2 conversations')).toBeInTheDocument();
    });

    it('renders a readable label, not a blank/"?", when agent_name is empty (AP-309)', async () => {
        // The global chat list used to send agent_name:"" for failed-execution
        // threads, which rendered as a red "?" avatar with no name. The rail
        // must degrade to a neutral "Agent" label instead of an empty string.
        api.forge.listChats.mockResolvedValue([
            { agent_id: 'x1', agent_name: '', scope_key: 'chat:default',
              label: 'General', last_message: '⚠ Agent execution failed: Not logged in',
              last_used_at: '2026-06-19T00:00:01.000Z' },
        ]);
        render(<Chat />);
        await waitFor(() => expect(api.forge.listChats).toHaveBeenCalled());
        expect((await screen.findAllByText('Agent')).length).toBeGreaterThan(0);
    });

    it('gives user and agent bubbles distinct, token-based surfaces', async () => {
        api.forge.listMessages.mockResolvedValue([
            { id: 'm1', role: 'user', content: 'my question', created_at: '2026-06-19T00:00:01.000Z' },
            { id: 'm2', role: 'assistant', content: 'agent reply', created_at: '2026-06-19T00:00:02.000Z' },
        ]);
        render(<Chat />);
        const userBubble = (await screen.findByText('my question')).closest('div[class*="max-w-"]');
        const agentBubble = (await screen.findByText('agent reply')).closest('div[class*="max-w-"]');
        // User bubble = soft lavender tint; agent = neutral card. Distinct, and
        // neither is the old glaring solid accent fill.
        expect(userBubble.style.background).toBe('var(--tint-lavender)');
        expect(agentBubble.style.background).toBe('var(--bg-card)');
        expect(userBubble.style.background).not.toBe(agentBubble.style.background);
    });

    it('switches scope via the per-agent conversation selector', async () => {
        api.forge.listChats.mockResolvedValue([
            { agent_id: 'a1', agent_name: 'Conductor', scope_key: 'chat:project:p1',
              label: 'About Smoke', last_message: 'on it', last_used_at: '2026-06-19T00:00:03.000Z' },
            { agent_id: 'a1', agent_name: 'Conductor', scope_key: 'chat:default',
              label: 'General', last_message: 'hi', last_used_at: '2026-06-19T00:00:02.000Z' },
        ]);
        render(<Chat />);
        // Newest scope auto-selected → its messages load.
        await waitFor(() => {
            const call = api.forge.listMessages.mock.calls.find(
                ([id, p]) => id === 'a1' && p.scope_key === 'chat:project:p1');
            expect(call).toBeTruthy();
        });
        // Open the selector (its button shows the active scope label) and pick
        // the other conversation.
        fireEvent.click(screen.getByTitle('Switch conversation'));
        fireEvent.click(await screen.findByText('General'));
        await waitFor(() => {
            const call = api.forge.listMessages.mock.calls.find(
                ([id, p]) => id === 'a1' && p.scope_key === 'chat:default');
            expect(call).toBeTruthy();
        });
    });
});
