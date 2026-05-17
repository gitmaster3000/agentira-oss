import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Sparkles, X, Send, Loader, GripVertical } from 'lucide-react';
import { api } from '../api';

// Each agent's floating-chat thread is its own workspace-wide conversation.
const CHAT_SCOPE = 'chat:default';
const POLL_MS = 3000;
const PANEL_W = 380;
const PANEL_H = 520;
const POS_KEY = 'agentira.floatingChat.pos';

/**
 * FloatingChat — a movable, multi-agent chat dock.
 *
 * A floating button opens a chat panel. The panel is draggable (by its
 * header) and remembers where you put it. An agent picker lets you talk
 * to the Agentira Guide (default), the Conductor, or any other agent in
 * the workspace. Mounted on both Studio and Forge layouts.
 */
export function FloatingChat() {
    const [open, setOpen] = useState(false);
    const [agents, setAgents] = useState([]);
    const [guideId, setGuideId] = useState(null);
    const [selectedId, setSelectedId] = useState(null);
    const [unavailable, setUnavailable] = useState(false);
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [sending, setSending] = useState(false);
    const [pos, setPos] = useState(null);   // {x, y} top-left, px
    const bottomRef = useRef(null);
    const inputRef = useRef(null);
    const dragRef = useRef(null);            // {dx, dy} while dragging

    // ── position: load saved / default to bottom-right ──────────────────
    useEffect(() => {
        const clamp = (p) => ({
            x: Math.min(Math.max(8, p.x), window.innerWidth - PANEL_W - 8),
            y: Math.min(Math.max(8, p.y), window.innerHeight - PANEL_H - 8),
        });
        try {
            const saved = JSON.parse(localStorage.getItem(POS_KEY) || 'null');
            if (saved && typeof saved.x === 'number') {
                setPos(clamp(saved));
                return;
            }
        } catch { /* ignore */ }
        setPos(clamp({
            x: window.innerWidth - PANEL_W - 20,
            y: window.innerHeight - PANEL_H - 20,
        }));
    }, []);

    const onDragStart = (e) => {
        if (!pos) return;
        dragRef.current = { dx: e.clientX - pos.x, dy: e.clientY - pos.y };
        const onMove = (ev) => {
            const d = dragRef.current;
            if (!d) return;
            setPos({
                x: Math.min(Math.max(8, ev.clientX - d.dx),
                            window.innerWidth - PANEL_W - 8),
                y: Math.min(Math.max(8, ev.clientY - d.dy),
                            window.innerHeight - PANEL_H - 8),
            });
        };
        const onUp = () => {
            window.removeEventListener('mousemove', onMove);
            window.removeEventListener('mouseup', onUp);
            dragRef.current = null;
            setPos((p) => {
                if (p) localStorage.setItem(POS_KEY, JSON.stringify(p));
                return p;
            });
        };
        window.addEventListener('mousemove', onMove);
        window.addEventListener('mouseup', onUp);
    };

    // ── resolve the agent roster the first time the panel opens ─────────
    useEffect(() => {
        if (!open || guideId || unavailable) return;
        Promise.all([
            api.forge.getConcierge().catch(() => null),
            api.forge.listAgents().catch(() => []),
        ]).then(([guide, list]) => {
            if (!guide) { setUnavailable(true); return; }
            const roster = Array.isArray(list) ? [...list] : [];
            if (!roster.some((a) => a.id === guide.id)) roster.unshift(guide);
            // Guide first, Conductor next, then the rest by name.
            roster.sort((a, b) => {
                const rank = (x) => x.id === guide.id ? 0
                    : x.name === 'Conductor' ? 1 : 2;
                return rank(a) - rank(b) || (a.name || '').localeCompare(b.name || '');
            });
            setGuideId(guide.id);
            setAgents(roster);
            setSelectedId((cur) => cur || guide.id);
        });
    }, [open, guideId, unavailable]);

    const loadMessages = useCallback(async () => {
        if (!selectedId) return;
        try {
            const data = await api.forge.listMessages(selectedId, {
                limit: 100, scope_key: CHAT_SCOPE,
            });
            if (Array.isArray(data)) setMessages(data);
        } catch { /* transient */ }
    }, [selectedId]);

    // Poll the selected agent's thread while the panel is open.
    useEffect(() => {
        if (!open || !selectedId) return;
        setMessages([]);
        loadMessages();
        const t = setInterval(loadMessages, POLL_MS);
        return () => clearInterval(t);
    }, [open, selectedId, loadMessages]);

    useEffect(() => {
        if (open) bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages.length, open]);

    useEffect(() => {
        if (open) inputRef.current?.focus();
    }, [open, selectedId]);

    const send = async () => {
        const trimmed = input.trim();
        if (!trimmed || sending || !selectedId) return;
        const localId = `local-${Date.now()}`;
        setMessages((prev) => [...prev, {
            id: localId, role: 'user', content: trimmed,
            created_at: new Date().toISOString(),
        }]);
        setInput('');
        setSending(true);
        try {
            await api.forge.sendRuntimeChat(selectedId, {
                content: trimmed,
                scope_key: CHAT_SCOPE,
                user_context: {
                    surface: 'floating_chat',
                    route: window.location.pathname,
                },
            });
            setMessages((prev) => prev.filter((m) => m.id !== localId));
            await loadMessages();
        } catch (err) {
            console.error('Floating chat send failed:', err);
        } finally {
            setSending(false);
            inputRef.current?.focus();
        }
    };

    const lastIsUser = messages.length > 0
        && messages[messages.length - 1].role === 'user';
    const selectedAgent = agents.find((a) => a.id === selectedId);

    if (!open) {
        return (
            <button
                onClick={() => setOpen(true)}
                className="fixed bottom-5 right-5 z-50 flex items-center gap-2 px-4 py-3 rounded-full bg-accent-primary text-white shadow-lg hover:brightness-110 transition-all"
                title="Open agent chat"
            >
                <Sparkles className="w-5 h-5" />
                <span className="text-sm font-medium">Ask Agentira</span>
            </button>
        );
    }

    return (
        <div
            className="fixed z-50 flex flex-col rounded-xl bg-bg-app border border-border-subtle shadow-2xl"
            style={{
                left: pos ? pos.x : undefined,
                top: pos ? pos.y : undefined,
                width: PANEL_W, height: PANEL_H,
                maxWidth: 'calc(100vw - 1rem)', maxHeight: 'calc(100vh - 1rem)',
            }}
        >
            {/* Header — drag handle */}
            <div
                onMouseDown={onDragStart}
                className="flex items-center gap-2 px-3 py-2.5 border-b border-border-subtle cursor-move select-none"
            >
                <GripVertical className="w-4 h-4 text-text-tertiary flex-shrink-0" />
                <div className="w-7 h-7 rounded-lg bg-accent-subtle flex items-center justify-center flex-shrink-0">
                    <Sparkles className="w-4 h-4 text-accent-primary" />
                </div>
                {/* Agent picker */}
                <select
                    value={selectedId || ''}
                    onChange={(e) => setSelectedId(e.target.value)}
                    onMouseDown={(e) => e.stopPropagation()}
                    disabled={unavailable || agents.length === 0}
                    className="flex-1 min-w-0 bg-bg-hover border border-border-subtle rounded-md px-2 py-1 text-sm text-text-primary focus:outline-none focus:border-accent-primary"
                >
                    {agents.length === 0 && <option>Loading…</option>}
                    {agents.map((a) => (
                        <option key={a.id} value={a.id}>
                            {a.name}{a.id === guideId ? ' (Guide)' : ''}
                        </option>
                    ))}
                </select>
                <button
                    onClick={() => setOpen(false)}
                    onMouseDown={(e) => e.stopPropagation()}
                    className="p-1 rounded hover:bg-bg-hover text-text-tertiary hover:text-text-primary flex-shrink-0"
                    title="Close"
                >
                    <X className="w-4 h-4" />
                </button>
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2">
                {unavailable && (
                    <div className="text-xs text-text-tertiary text-center py-6">
                        Chat isn't available right now.
                    </div>
                )}
                {!unavailable && messages.length === 0 && (
                    <div className="text-sm text-text-secondary text-center py-8 px-4">
                        {selectedId === guideId
                            ? "Hi! I'm the Agentira Guide. Ask me how anything in Agentira works — or what's on your current screen."
                            : `Chatting with ${selectedAgent?.name || 'this agent'}.`}
                    </div>
                )}
                {messages.map((m) => <ChatBubble key={m.id} m={m} />)}
                {lastIsUser && (
                    <div className="flex items-center gap-1.5 px-2 text-xs text-text-tertiary">
                        <Loader className="w-3 h-3 animate-spin" />
                        {selectedAgent?.name || 'Agent'} is thinking…
                    </div>
                )}
                <div ref={bottomRef} />
            </div>

            {/* Input */}
            <div className="p-3 border-t border-border-subtle">
                <div className="flex items-end gap-2">
                    <textarea
                        ref={inputRef}
                        rows={1}
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && !e.shiftKey) {
                                e.preventDefault();
                                send();
                            }
                        }}
                        placeholder={unavailable ? 'Unavailable' : 'Type a message…'}
                        disabled={unavailable || !selectedId}
                        className="flex-1 resize-none bg-bg-hover border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-primary disabled:opacity-50 max-h-28"
                    />
                    <button
                        onClick={send}
                        disabled={!input.trim() || sending || unavailable || !selectedId}
                        className="p-2 rounded-lg bg-accent-primary text-white disabled:opacity-40 hover:brightness-110"
                        title="Send"
                    >
                        <Send className="w-4 h-4" />
                    </button>
                </div>
            </div>
        </div>
    );
}

function ChatBubble({ m }) {
    const role = m.role || 'assistant';
    if (role === 'system') {
        return (
            <div className="text-[11px] text-text-tertiary text-center px-4 py-1">
                {m.content}
            </div>
        );
    }
    if (role === 'tool') {
        const label = m.tool_name
            ? `Used ${m.tool_name}`
            : (m.content || m.tool_output || 'tool');
        return (
            <div className="text-[11px] text-text-tertiary px-2 font-mono truncate">
                {label}
            </div>
        );
    }
    const isUser = role === 'user';
    return (
        <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
            <div
                className={`max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap break-words ${
                    isUser
                        ? 'bg-accent-primary text-white'
                        : 'bg-bg-hover text-text-primary'
                }`}
            >
                {m.content || '…'}
            </div>
        </div>
    );
}
