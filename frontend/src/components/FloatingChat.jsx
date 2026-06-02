import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Sparkles, X, Send, Loader, GripVertical, Ban } from 'lucide-react';
import { api } from '../api';
import { AskUserQuestionCard } from './AskUserQuestionCard';

// Each agent's floating-chat thread is its own workspace-wide conversation.
const CHAT_SCOPE = 'chat:default';
const POLL_MS = 3000;
const PANEL_W = 380;
const PANEL_H = 520;
const BTN = 52;                  // collapsed-button diameter, px
const POS_KEY = 'agentira.floatingChat.pos';

// Clamp a top-left point so a w×h element stays fully on-screen.
function clampPos(p, w, h) {
    return {
        x: Math.min(Math.max(8, p.x), window.innerWidth - w - 8),
        y: Math.min(Math.max(8, p.y), window.innerHeight - h - 8),
    };
}

/**
 * FloatingChat — a movable, multi-agent chat dock.
 *
 * The collapsed icon button and the open chat panel share ONE position
 * anchor — drag either and the other follows; it's remembered across
 * sessions. The panel has an agent picker (Agentira Guide / Conductor /
 * any workspace agent) and a Stop control. Mounted on Studio + Forge.
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
    // Latches the thinking indicator off after a Stop click. Reset on
    // the next send — otherwise the heuristic ("last message is user's")
    // re-asserts thinking even though the user has cancelled.
    const [stopped, setStopped] = useState(false);
    // One shared anchor (top-left) for both the button and the panel.
    const [pos, setPos] = useState(null);
    const bottomRef = useRef(null);
    const inputRef = useRef(null);

    // ── load the saved anchor / default to the bottom-right corner ──────
    useEffect(() => {
        let initial = null;
        try {
            const saved = JSON.parse(localStorage.getItem(POS_KEY) || 'null');
            if (saved && typeof saved.x === 'number') initial = saved;
        } catch { /* ignore */ }
        if (!initial) {
            initial = { x: window.innerWidth - BTN - 20,
                        y: window.innerHeight - BTN - 20 };
        }
        setPos(clampPos(initial, BTN, BTN));
    }, []);

    // Shared drag wiring — used by both the button and the panel header,
    // writing the SAME `pos`. `onClick` (when given) fires only on a
    // no-move mouseup, so the button is both draggable and clickable.
    const startDrag = (e, cur, w, h, onClick) => {
        if (!cur) return;
        const origin = { x: e.clientX, y: e.clientY };
        const off = { dx: e.clientX - cur.x, dy: e.clientY - cur.y, moved: false };
        const onMove = (ev) => {
            if (Math.abs(ev.clientX - origin.x)
                + Math.abs(ev.clientY - origin.y) > 4) off.moved = true;
            setPos(clampPos({ x: ev.clientX - off.dx, y: ev.clientY - off.dy }, w, h));
        };
        const onUp = () => {
            window.removeEventListener('mousemove', onMove);
            window.removeEventListener('mouseup', onUp);
            if (off.moved) {
                setPos((p) => {
                    if (p) localStorage.setItem(POS_KEY, JSON.stringify(p));
                    return p;
                });
            } else if (onClick) {
                onClick();
            }
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

    // Shared post path — used by the input box (send) and by clickable
    // AskUserQuestion answers (onAnswer).
    const postMessage = async (content) => {
        const text = (content || '').trim();
        if (!text || !selectedId) return;
        const localId = `local-${Date.now()}`;
        setStopped(false);
        setMessages((prev) => [...prev, {
            id: localId, role: 'user', content: text,
            created_at: new Date().toISOString(),
        }]);
        setSending(true);
        try {
            await api.forge.sendRuntimeChat(selectedId, {
                content: text,
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

    const send = async () => {
        if (!input.trim() || sending || !selectedId) return;
        const trimmed = input.trim();
        setInput('');
        await postMessage(trimmed);
    };

    const stop = async () => {
        if (!selectedId) return;
        setStopped(true);
        setMessages((prev) => [...prev, {
            id: `local-stop-${Date.now()}`, role: 'system',
            content: '⏹ Stopped.', created_at: new Date().toISOString(),
        }]);
        try {
            await api.forge.stopChat(selectedId, CHAT_SCOPE);
        } catch (err) {
            console.error('Stop failed:', err);
        }
        loadMessages().catch(() => {});
    };

    // "Thinking" = last message is user's with no reply, capped at 10 min,
    // and forcibly cleared after a Stop click until the next send.
    const _last = messages[messages.length - 1];
    const lastIsUser = !stopped && !!_last && _last.role === 'user'
        && _last.created_at
        && (Date.now() - new Date(_last.created_at).getTime()) < 10 * 60 * 1000;
    const selectedAgent = agents.find((a) => a.id === selectedId);

    // Both elements derive their on-screen position from the one anchor.
    const btnXY = pos ? clampPos(pos, BTN, BTN) : null;
    const panelXY = pos ? clampPos(pos, PANEL_W, PANEL_H) : null;

    // ── collapsed: a small, draggable icon button ───────────────────────
    if (!open) {
        return (
            <button
                onMouseDown={(e) => startDrag(e, btnXY, BTN, BTN, () => setOpen(true))}
                className="fixed z-50 flex items-center justify-center rounded-full bg-accent-primary text-white shadow-lg hover:brightness-110 cursor-pointer"
                style={{ left: btnXY?.x, top: btnXY?.y, width: BTN, height: BTN }}
                title="Ask Agentira — click to open, drag to move"
            >
                <Sparkles className="w-5 h-5" />
            </button>
        );
    }

    return (
        <div
            className="fixed z-50 flex flex-col rounded-xl bg-bg-app border border-border-subtle shadow-2xl"
            style={{
                left: panelXY ? panelXY.x : undefined,
                top: panelXY ? panelXY.y : undefined,
                width: PANEL_W, height: PANEL_H,
                maxWidth: 'calc(100vw - 1rem)', maxHeight: 'calc(100vh - 1rem)',
            }}
        >
            {/* Header — drag handle */}
            <div
                onMouseDown={(e) => startDrag(e, panelXY, PANEL_W, PANEL_H)}
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
                {messages.map((m) => <ChatBubble key={m.id} m={m} onAnswer={postMessage} />)}
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
                    {/* Stop while the agent is working, Send otherwise. */}
                    {lastIsUser ? (
                        <button
                            onClick={stop}
                            className="p-2 rounded-lg bg-red-500/15 text-red-400 hover:bg-red-500/25"
                            title="Stop"
                        >
                            <Ban className="w-4 h-4" />
                        </button>
                    ) : (
                        <button
                            onClick={send}
                            disabled={!input.trim() || sending || unavailable || !selectedId}
                            className="p-2 rounded-lg bg-accent-primary text-white disabled:opacity-40 hover:brightness-110"
                            title="Send"
                        >
                            <Send className="w-4 h-4" />
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
}

function ChatBubble({ m, onAnswer }) {
    const role = m.role || 'assistant';
    if (role === 'system') {
        return (
            <div className="text-[11px] text-text-tertiary text-center px-4 py-1">
                {m.content}
            </div>
        );
    }
    if (role === 'tool') {
        if (m.tool_name === 'AskUserQuestion') {
            return <AskUserQuestionCard toolInput={m.tool_input} onAnswer={onAnswer} />;
        }
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
