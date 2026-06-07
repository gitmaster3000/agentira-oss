import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { FloatingChat } from './FloatingChat';
import { api } from '../api';

vi.mock('../api', () => ({
    api: {
        forge: {
            getConcierge: vi.fn(),
            listAgents: vi.fn(),
            listMessages: vi.fn(),
            listConversations: vi.fn(),
            sendRuntimeChat: vi.fn(),
            stopChat: vi.fn(),
        },
    },
}));

// jsdom doesn't implement scrollIntoView, which the dock calls on each new turn.
window.HTMLElement.prototype.scrollIntoView = vi.fn();

// Drag-open: the collapsed button opens on a no-move mousedown→mouseup. The
// mouseup listener is attached to window, so dispatch it there.
function openDock() {
    const btn = screen.getByTitle(/Ask Agentira/i);
    fireEvent.mouseDown(btn);
    fireEvent.mouseUp(window);
}

describe('FloatingChat', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.forge.getConcierge.mockResolvedValue({ id: 'guide', name: 'Guide' });
        api.forge.listAgents.mockResolvedValue([]);
        api.forge.listConversations.mockResolvedValue([
            { scope_key: 'chat:default', message_count: 120 },
        ]);
    });

    it('loads the live tail with a paginated limit and shows loaded/total count', async () => {
        api.forge.listMessages.mockResolvedValue([
            { id: 's1', role: 'user', content: 'hi', created_at: '2026-06-07T00:00:01.000Z' },
            { id: 's2', role: 'assistant', content: 'hello', created_at: '2026-06-07T00:00:02.000Z' },
        ]);

        render(<FloatingChat />);
        openDock();

        // Tail fetch uses a windowed limit (not a flat 100) for chat:default.
        await waitFor(() => expect(api.forge.listMessages).toHaveBeenCalled());
        const tailCall = api.forge.listMessages.mock.calls.find(
            ([, p]) => p && p.offset === undefined,
        );
        expect(tailCall[1]).toMatchObject({ limit: 50, scope_key: 'chat:default' });
        expect(tailCall[1].limit).toBeLessThan(100);

        // Header shows loaded-window / total-thread, not just the loaded count.
        await waitFor(() => expect(screen.getByText('2/120')).toBeInTheDocument());
    });

    it('fetches an older page with an offset when scrolled to the top', async () => {
        // A full first page so the window believes more history exists.
        const page = Array.from({ length: 50 }, (_, i) => ({
            id: `s${i}`,
            role: 'assistant',
            content: `m${i}`,
            created_at: `2026-06-07T00:01:${String(i % 60).padStart(2, '0')}.000Z`,
        }));
        api.forge.listMessages.mockResolvedValue(page);

        render(<FloatingChat />);
        openDock();

        await waitFor(() =>
            expect(screen.getByText(/Scroll up for older messages/i)).toBeInTheDocument(),
        );

        const scroller = screen.getByText(/Scroll up for older messages/i).parentElement;
        // Force the scroll-to-top condition and fire the handler.
        Object.defineProperty(scroller, 'scrollTop', { value: 0, writable: true });
        fireEvent.scroll(scroller);

        await waitFor(() => {
            const olderCall = api.forge.listMessages.mock.calls.find(
                ([, p]) => p && p.offset === 50,
            );
            expect(olderCall).toBeTruthy();
            expect(olderCall[1]).toMatchObject({ limit: 50, scope_key: 'chat:default' });
        });
    });
});
