import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { Chat } from './Chat';
import { api } from '../api';

vi.mock('../api', () => ({
    api: {
        forge: {
            listChats: vi.fn(),
            listMessages: vi.fn(),
            sendRuntimeChat: vi.fn(),
            stopChat: vi.fn(),
            scopeLive: vi.fn(),
            listAgents: vi.fn(),
            clearConversation: vi.fn(),
            getDispatchPreview: vi.fn(),
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
        api.forge.scopeLive.mockResolvedValue({ live: false });
        api.forge.stopChat.mockResolvedValue({});
        api.forge.listAgents.mockResolvedValue([
            { id: 'a1', name: 'Conductor' },
            { id: 'a2', name: 'Implementer' },
            { id: 'a3', name: 'Reviewer' },
        ]);
        api.forge.clearConversation.mockResolvedValue({});
        api.forge.getDispatchPreview.mockResolvedValue({
            agent: { name: 'Conductor', runtime_provider: 'claude', model: 'sonnet' },
            project: {},
            mcp_servers: [],
            env_vars: { injected_by_daemon: [], user_provided_names: [] },
            system_prompt_addenda: {},
        });
        window.confirm = vi.fn(() => true);
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
        const box = await screen.findByPlaceholderText(/message/i);
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

    // The reported bug: the unified chat's Stop button used to depend solely on
    // "the last message is the user's", so it vanished the instant the agent
    // posted a reply — even mid-turn. It must instead track the daemon's
    // live-turn mirror (scopeLive), matching the per-agent chat.
    it('shows Stop while the scope is live even when the last message is an agent reply', async () => {
        api.forge.listMessages.mockResolvedValue([
            { id: 'm1', role: 'user', content: 'go', created_at: '2026-06-19T00:00:01.000Z' },
            { id: 'm2', role: 'assistant', content: 'working on it', created_at: '2026-06-19T00:00:02.000Z' },
        ]);
        api.forge.scopeLive.mockResolvedValue({ live: true });
        render(<Chat />);
        await waitFor(() => expect(api.forge.scopeLive).toHaveBeenCalledWith('a1', 'chat:project:p1'));
        // Stop button (title="Stop") is present, Send is not, and the thinking
        // indicator shows — all driven by scopeLive, not the message role.
        expect(await screen.findByTitle('Stop')).toBeInTheDocument();
        expect(screen.queryByTitle('Send')).not.toBeInTheDocument();
        expect(screen.getByText(/is thinking/i)).toBeInTheDocument();
    });

    it('shows Send (not Stop) when the scope is idle and the agent has replied', async () => {
        api.forge.listMessages.mockResolvedValue([
            { id: 'm1', role: 'user', content: 'go', created_at: '2026-06-19T00:00:01.000Z' },
            { id: 'm2', role: 'assistant', content: 'all done', created_at: '2026-06-19T00:00:02.000Z' },
        ]);
        api.forge.scopeLive.mockResolvedValue({ live: false });
        render(<Chat />);
        await waitFor(() => expect(api.forge.scopeLive).toHaveBeenCalled());
        expect(await screen.findByTitle('Send')).toBeInTheDocument();
        expect(screen.queryByTitle('Stop')).not.toBeInTheDocument();
    });

    it('pressing Stop cancels the live turn and latches the button off', async () => {
        api.forge.listMessages.mockResolvedValue([
            { id: 'm1', role: 'user', content: 'go', created_at: '2026-06-19T00:00:01.000Z' },
        ]);
        api.forge.scopeLive.mockResolvedValue({ live: true });
        render(<Chat />);
        const stopBtn = await screen.findByTitle('Stop');
        fireEvent.click(stopBtn);
        await waitFor(() => expect(api.forge.stopChat).toHaveBeenCalledWith('a1', 'chat:project:p1'));
        // Latched off immediately even though scopeLive still reports live.
        await waitFor(() => expect(screen.queryByTitle('Stop')).not.toBeInTheDocument());
        expect(screen.getByTitle('Send')).toBeInTheDocument();
    });

    // AP-436: global Chat page must support the same slash commands as AgentDetail.
    it('/clear wipes the selected conversation without sending a message', async () => {
        render(<Chat />);
        await screen.findAllByText('Conductor');
        const box = await screen.findByPlaceholderText(/message/i);
        fireEvent.change(box, { target: { value: '/clear' } });
        fireEvent.keyDown(box, { key: 'Enter' });
        await waitFor(() => {
            expect(api.forge.clearConversation).toHaveBeenCalledWith('a1', 'chat:project:p1');
        });
        expect(api.forge.sendRuntimeChat).not.toHaveBeenCalled();
    });

    it('/context shows a dispatch preview and does not send', async () => {
        render(<Chat />);
        await screen.findAllByText('Conductor');
        const box = await screen.findByPlaceholderText(/message/i);
        fireEvent.change(box, { target: { value: '/context' } });
        fireEvent.keyDown(box, { key: 'Enter' });
        await waitFor(() => {
            expect(api.forge.getDispatchPreview).toHaveBeenCalledWith('a1', 'p1');
        });
        expect(api.forge.sendRuntimeChat).not.toHaveBeenCalled();
        expect(await screen.findByText(/\/context/)).toBeInTheDocument();
    });

    it('sidebar New chat starts a fresh general thread for the picked agent', async () => {
        render(<Chat />);
        await screen.findAllByText('Conductor');
        fireEvent.click(screen.getByTitle('New chat'));
        expect(await screen.findByText(/New chat with/i)).toBeInTheDocument();
        // Pick an agent that already has chat:default → new scope must be chat:user:*
        // Flyout lists roster agents by name only (no last-message preview).
        const flyoutAgents = screen.getAllByRole('button').filter(
            (b) => b.textContent?.trim() === 'IMImplementer' || b.textContent?.includes('Implementer'),
        );
        // Prefer the flyout row (short label) over the rail row (has preview text).
        const flyout = flyoutAgents.find((b) => !b.textContent?.includes('done')) || flyoutAgents[0];
        fireEvent.click(flyout);
        await waitFor(() => {
            const call = api.forge.listMessages.mock.calls.find(
                ([id, p]) => id === 'a2' && String(p.scope_key).startsWith('chat:user:'));
            expect(call).toBeTruthy();
        });
    });

    it('Send uses themed btn-primary classes', async () => {
        api.forge.listMessages.mockResolvedValue([
            { id: 'm1', role: 'assistant', content: 'done', created_at: '2026-06-19T00:00:02.000Z' },
        ]);
        api.forge.scopeLive.mockResolvedValue({ live: false });
        render(<Chat />);
        const send = await screen.findByTitle('Send');
        expect(send.className).toMatch(/btn/);
        expect(send.className).toMatch(/btn-primary/);
    });

    it('Stop uses themed btn-ghost classes', async () => {
        api.forge.listMessages.mockResolvedValue([
            { id: 'm1', role: 'user', content: 'go', created_at: '2026-06-19T00:00:01.000Z' },
        ]);
        api.forge.scopeLive.mockResolvedValue({ live: true });
        render(<Chat />);
        const stop = await screen.findByTitle('Stop');
        expect(stop.className).toMatch(/btn/);
        expect(stop.className).toMatch(/btn-ghost/);
    });

    it('conversations dropdown scrolls inside a max height (does not grow the page)', async () => {
        // Many scopes for one agent — the switcher must cap height + overflow-y.
        api.forge.listChats.mockResolvedValue(
            Array.from({ length: 40 }, (_, i) => ({
                agent_id: 'a1',
                agent_name: 'Conductor',
                scope_key: `chat:user:scope${i}`,
                label: `Chat ${i}`,
                last_message: `msg ${i}`,
                last_used_at: `2026-06-19T00:00:${String(i).padStart(2, '0')}.000Z`,
            })),
        );
        render(<Chat />);
        await waitFor(() => expect(api.forge.listChats).toHaveBeenCalled());
        // Wait for the resolved list to render, not just for the call — under
        // load (e.g. right after the backend suite in scripts/verify.sh) the
        // switcher isn't in the DOM yet when listChats has merely been called.
        fireEvent.click(await screen.findByTitle('Switch conversation'));
        const menu = await screen.findByTestId('conversations-dropdown');
        expect(menu.style.maxHeight).toMatch(/360px|70vh/);
        expect(menu.className).toMatch(/overflow-hidden/);
        // The list region (not the New chat footer) owns the scroll.
        const scrollRegion = menu.querySelector('.overflow-y-auto');
        expect(scrollRegion).toBeTruthy();
        expect(scrollRegion.className).toMatch(/overscroll-contain/);
        expect(within(menu).getByText('Chat 0')).toBeInTheDocument();
        expect(within(menu).getByText('Chat 39')).toBeInTheDocument();
    });

    it('new-chat agent picker also scrolls inside a max height', async () => {
        api.forge.listAgents.mockResolvedValue(
            Array.from({ length: 30 }, (_, i) => ({ id: `ag${i}`, name: `Agent ${i}` })),
        );
        render(<Chat />);
        await screen.findAllByText('Conductor');
        fireEvent.click(screen.getByTitle('New chat'));
        const menu = await screen.findByTestId('new-chat-dropdown');
        expect(menu.style.maxHeight).toMatch(/360px|70vh/);
        const scrollRegion = menu.querySelector('.overflow-y-auto');
        expect(scrollRegion).toBeTruthy();
    });

    it('composer is a textarea that auto-grows with multi-line text up to a max', async () => {
        render(<Chat />);
        const box = await screen.findByPlaceholderText(/message/i);
        expect(box.tagName).toBe('TEXTAREA');
        // jsdom doesn't layout scrollHeight; stub so the grow effect is observable.
        Object.defineProperty(box, 'scrollHeight', { configurable: true, get: () => 120 });
        fireEvent.change(box, { target: { value: 'line1\nline2\nline3' } });
        await waitFor(() => {
            expect(box.style.height).toBe('120px');
            expect(box.style.overflowY).toBe('hidden');
        });
        Object.defineProperty(box, 'scrollHeight', { configurable: true, get: () => 300 });
        fireEvent.change(box, { target: { value: 'line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nline10\nline11\nline12' } });
        await waitFor(() => {
            // Cap is 176px; past that we allow internal scroll.
            expect(box.style.height).toBe('176px');
            expect(box.style.overflowY).toBe('auto');
        });
    });

    // AP-509: a "needs input" notification / Needs-you card deep-links here.
    describe('agent questions', () => {
        const QUESTION = {
            id: 'q1', role: 'tool', tool_name: 'AskUserQuestion',
            content: 'Which colour?', created_at: '2026-06-19T00:00:03.000Z',
            tool_input: JSON.stringify({ questions: [{
                question: 'Which colour?', options: [{ label: 'Blue' }, { label: 'Green' }],
            }] }),
        };
        afterEach(() => window.history.pushState({}, '', '/'));

        it('opens the conversation named in ?agent=&scope= directly', async () => {
            window.history.pushState({}, '', '/chat?agent=a3&scope=task:t1');
            render(<Chat />);
            await waitFor(() => expect(api.forge.listMessages).toHaveBeenCalledWith(
                'a3', expect.objectContaining({ scope_key: 'task:t1' })));
            expect((await screen.findAllByText('Reviewer')).length).toBeGreaterThan(0);
        });

        it('answers a question by clicking an option, in that conversation', async () => {
            window.history.pushState({}, '', '/chat?agent=a3&scope=task:t1');
            api.forge.listMessages.mockResolvedValue([QUESTION]);
            render(<Chat />);
            fireEvent.click(await screen.findByRole('button', { name: /Blue/ }));
            await waitFor(() => expect(api.forge.sendRuntimeChat).toHaveBeenCalledWith(
                'a3', expect.objectContaining({ content: 'Blue', scope_key: 'task:t1' })));
        });

        it('keeps an already-answered question read-only after reload', async () => {
            window.history.pushState({}, '', '/chat?agent=a3&scope=task:t1');
            api.forge.listMessages.mockResolvedValue([QUESTION, {
                id: 'u1', role: 'user', content: 'Blue', created_at: '2026-06-19T00:00:04.000Z',
            }]);
            render(<Chat />);
            await screen.findByText('Green');
            expect(screen.queryByRole('button', { name: /Green/ })).toBeNull();
        });
    });
});
