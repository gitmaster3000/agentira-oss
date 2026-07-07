import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Send, Loader, Ban, MessageSquare, ChevronDown, ChevronLeft, Check } from 'lucide-react';
import { api } from '../api';
import { AskUserQuestionCard } from '../components/AskUserQuestionCard';
import { Markdown } from '../components/Markdown';
import { mergeWindow, serverLoadedCount } from '../lib/chatPagination';

// Global Chat page (design §2.4): the left rail lists one row per AGENT (not one
// row per conversation). Picking an agent opens its most-recent thread; the
// per-agent "Conversation" selector at the top of the pane switches between
// that agent's scoped chats (General / project / task). Reuses the FloatingChat
// message loading/sending logic, scoped to the picked (agent_id, scope_key).
const POLL_MS = 3000;
const PAGE_SIZE = 50;
const PREFETCH_PX = 120;

function relTime(iso) {
    if (!iso) return '';
    const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 60) return 'now';
    if (s < 3600) return `${Math.floor(s / 60)}m`;
    if (s < 86400) return `${Math.floor(s / 3600)}h`;
    return `${Math.floor(s / 86400)}d`;
}

// Stable color per agent name (matches the hashed-avatar convention used
// elsewhere in the app).
function agentColor(name) {
    let h = 0;
    for (let i = 0; i < (name || '').length; i++) h = (h * 31 + name.charCodeAt(i)) % 360;
    return `hsl(${h} 55% 55%)`;
}

// Collapse the flat (agent_id, scope_key) conversation rows into one entry per
// agent — preserving GET /forge/chats' newest-first order — so the left rail
// shows agents, and each agent carries its own list of scoped conversations.
function groupByAgent(convos) {
    const byId = new Map();
    const agents = [];
    for (const c of convos) {
        let a = byId.get(c.agent_id);
        if (!a) {
            a = { agent_id: c.agent_id, agent_name: c.agent_name, scopes: [] };
            byId.set(c.agent_id, a);
            agents.push(a);
        }
        a.scopes.push(c);
    }
    return { agents, byId };
}

export function Chat() {
    const [convos, setConvos] = useState([]);
    const [convosLoading, setConvosLoading] = useState(true);   // first load only
    const [sel, setSel] = useState(null);          // {agent_id, scope_key, agent_name, label}
    const [scopeOpen, setScopeOpen] = useState(false);
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [sending, setSending] = useState(false);
    const [stopped, setStopped] = useState(false);
    // ADR 009 / E2: daemon-reported "a turn is live for this scope" — the same
    // restart-proof signal the per-agent chat (AgentDetail) uses to keep Stop
    // visible the whole time the agent works. Replaces the old lastIsUser-only
    // heuristic, which dropped the button the instant any agent/tool message
    // landed (or after 10 min) even while the turn was still running.
    const [scopeLive, setScopeLive] = useState(false);
    // Mobile is single-pane: false → agent list, true → the open thread.
    // Ignored on desktop (md+), where both panes show side by side.
    const [mobilePane, setMobilePane] = useState(false);

    const bottomRef = useRef(null);
    const inputRef = useRef(null);
    const containerRef = useRef(null);
    const messagesRef = useRef([]);
    const loadingOlderRef = useRef(false);
    const reachedStartRef = useRef(false);
    const lastIdRef = useRef(null);

    // ── conversation rows across all agents (GET /forge/chats) ──────────
    const loadConvos = useCallback(async () => {
        try {
            const data = await api.forge.listChats();
            if (Array.isArray(data)) {
                setConvos(data);
                // Default-select the newest conversation overall (data is
                // newest-first), i.e. the first agent's most-recent scope.
                setSel((cur) => cur || (data[0] ? {
                    agent_id: data[0].agent_id, scope_key: data[0].scope_key,
                    agent_name: data[0].agent_name, label: data[0].label,
                } : null));
            }
        } catch { /* transient */ }
        finally { setConvosLoading(false); }
    }, []);

    useEffect(() => {
        loadConvos();
        const t = setInterval(loadConvos, POLL_MS);
        return () => clearInterval(t);
    }, [loadConvos]);

    useEffect(() => { messagesRef.current = messages; }, [messages]);

    // ── messages for the selected conversation ──────────────────────────
    const loadMessages = useCallback(async () => {
        if (!sel) return;
        try {
            const data = await api.forge.listMessages(sel.agent_id, {
                limit: PAGE_SIZE, scope_key: sel.scope_key,
            });
            if (Array.isArray(data)) setMessages((prev) => mergeWindow(prev, data));
        } catch { /* transient */ }
    }, [sel]);

    const loadOlder = useCallback(async () => {
        if (!sel || loadingOlderRef.current || reachedStartRef.current) return;
        const offset = serverLoadedCount(messagesRef.current);
        if (offset === 0) return;
        loadingOlderRef.current = true;
        try {
            const older = await api.forge.listMessages(sel.agent_id, {
                limit: PAGE_SIZE, offset, scope_key: sel.scope_key,
            });
            if (!older || older.length === 0) { reachedStartRef.current = true; return; }
            if (older.length < PAGE_SIZE) reachedStartRef.current = true;
            const c = containerRef.current;
            const before = c ? c.scrollHeight : 0;
            setMessages((prev) => mergeWindow(prev, older));
            requestAnimationFrame(() => { if (c) c.scrollTop += (c.scrollHeight - before); });
        } catch { /* transient */ }
        finally { loadingOlderRef.current = false; }
    }, [sel]);

    // Reset + poll when the selected conversation changes.
    const selKey = sel ? `${sel.agent_id}|${sel.scope_key}` : null;
    useEffect(() => {
        if (!sel) return;
        setMessages([]);
        setStopped(false);          // don't carry a Stop latch across conversations
        reachedStartRef.current = false;
        loadingOlderRef.current = false;
        loadMessages();
        const t = setInterval(loadMessages, POLL_MS);
        return () => clearInterval(t);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [selKey]);

    // Poll the daemon's live-turn mirror for the selected conversation so Stop
    // stays available exactly while a turn runs — restart-proof, no staleness
    // guess. Mirrors AgentDetail's scopeLive poll.
    useEffect(() => {
        if (!sel) { setScopeLive(false); return; }
        let alive = true;
        const tick = async () => {
            try {
                const r = await api.forge.scopeLive(sel.agent_id, sel.scope_key);
                if (alive) setScopeLive(!!(r && r.live));
            } catch { if (alive) setScopeLive(false); }
        };
        tick();
        const t = setInterval(tick, POLL_MS);
        return () => { alive = false; clearInterval(t); };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [selKey]);

    const onScroll = useCallback(() => {
        const c = containerRef.current;
        if (c && c.scrollTop < PREFETCH_PX) loadOlder();
    }, [loadOlder]);

    const _lastId = messages.length ? messages[messages.length - 1].id : null;
    useEffect(() => {
        if (_lastId !== lastIdRef.current) {
            bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
        }
        lastIdRef.current = _lastId;
    }, [_lastId]);

    useEffect(() => { inputRef.current?.focus(); }, [selKey]);

    // Auto-grow the composer with its content (shrinks back when cleared);
    // the CSS max-height caps it and switches to scroll.
    useEffect(() => {
        const el = inputRef.current;
        if (!el) return;
        el.style.height = 'auto';
        el.style.height = `${el.scrollHeight}px`;
    }, [input]);

    const postMessage = async (content) => {
        const text = (content || '').trim();
        if (!text || !sel) return;
        const localId = `local-${Date.now()}`;
        setStopped(false);
        setMessages((prev) => [...prev, {
            id: localId, role: 'user', content: text, created_at: new Date().toISOString(),
        }]);
        setSending(true);
        try {
            await api.forge.sendRuntimeChat(sel.agent_id, {
                content: text,
                scope_key: sel.scope_key,
                user_context: { surface: 'chat_page', route: window.location.pathname },
            });
            setMessages((prev) => prev.filter((m) => m.id !== localId));
            await loadMessages();
        } catch (err) {
            console.error('Chat send failed:', err);
        } finally {
            setSending(false);
            inputRef.current?.focus();
        }
    };

    const send = async () => {
        if (!input.trim() || sending || !sel) return;
        const trimmed = input.trim();
        setInput('');
        await postMessage(trimmed);
    };

    const stop = async () => {
        if (!sel) return;
        setStopped(true);
        setMessages((prev) => [...prev, {
            id: `local-stop-${Date.now()}`, role: 'system',
            content: '⏹ Stopped.', created_at: new Date().toISOString(),
        }]);
        try { await api.forge.stopChat(sel.agent_id, sel.scope_key); }
        catch (err) { console.error('Stop failed:', err); }
        loadMessages().catch(() => {});
    };

    // Optimistic instant signal: right after a send, the user's local message
    // is the tail and the daemon mirror hasn't flipped yet — show Stop without
    // waiting for the first poll. The 10-min cap only bounds this optimistic
    // window; scopeLive (below) is the authoritative "still working" signal.
    const _last = messages[messages.length - 1];
    const lastIsUser = !!_last && _last.role === 'user' && _last.created_at
        && (Date.now() - new Date(_last.created_at).getTime()) < 10 * 60 * 1000;
    // Agent is working — show the Stop button and the thinking indicator. A
    // user-pressed Stop latches this off for the current view.
    const working = !stopped && (scopeLive || lastIsUser);

    const { agents, byId } = groupByAgent(convos);
    // The selected agent's own conversations drive the top scope selector.
    const selScopes = (sel && byId.get(sel.agent_id)?.scopes) || [];

    // Pick an agent → open its most-recent conversation.
    const pickAgent = (a) => {
        const top = a.scopes[0];
        setScopeOpen(false);
        setMobilePane(true);
        setSel({
            agent_id: a.agent_id, scope_key: top.scope_key,
            agent_name: a.agent_name, label: top.label,
        });
    };
    const pickScope = (c) => {
        setScopeOpen(false);
        setMobilePane(true);
        setSel({
            agent_id: c.agent_id, scope_key: c.scope_key,
            agent_name: c.agent_name, label: c.label,
        });
    };

    return (
        <div className="flex h-full min-h-0">
            {/* ── agent list (one row per agent) ────────────────────────── */}
            <aside className={`w-full md:w-72 flex-shrink-0 border-r border-border-subtle bg-bg-panel md:flex flex-col ${mobilePane ? 'hidden' : 'flex'}`}>
                <div className="px-4 h-[54px] flex-shrink-0 border-b border-border-subtle flex items-center gap-2">
                    <MessageSquare className="w-5 h-5 text-accent-primary" />
                    <span className="text-title-sm font-bold text-text-primary">Chat</span>
                    <span className="ml-auto text-[11px] text-text-tertiary">{agents.length} agents</span>
                </div>
                <div className="flex-1 overflow-y-auto">
                    {convosLoading && agents.length === 0 && (
                        <div className="flex items-center justify-center gap-2 text-xs text-text-tertiary py-8 px-4">
                            <Loader className="w-4 h-4 animate-spin" />
                            Loading conversations…
                        </div>
                    )}
                    {!convosLoading && agents.length === 0 && (
                        <div className="text-xs text-text-tertiary text-center py-8 px-4">
                            No conversations yet.
                        </div>
                    )}
                    {agents.map((a) => {
                        const active = sel && sel.agent_id === a.agent_id;
                        const top = a.scopes[0];
                        return (
                            <button
                                key={a.agent_id}
                                onClick={() => pickAgent(a)}
                                className={`w-full text-left px-3 py-2.5 border-b border-border-subtle flex gap-2.5
                                    ${active ? 'bg-accent-subtle' : 'hover:bg-bg-hover'}`}
                            >
                                <div
                                    className="w-8 h-8 rounded-lg flex-shrink-0 flex items-center justify-center text-white text-xs font-bold"
                                    style={{ background: agentColor(a.agent_name) }}
                                >
                                    {(a.agent_name || '?').slice(0, 2).toUpperCase()}
                                </div>
                                <div className="min-w-0 flex-1">
                                    <div className="flex items-center justify-between gap-2">
                                        <span className="text-sm font-medium text-text-primary truncate">
                                            {a.agent_name || 'Agent'}
                                        </span>
                                        <span className="text-[11px] text-text-tertiary flex-shrink-0">
                                            {relTime(top.last_used_at)}
                                        </span>
                                    </div>
                                    <div className="text-xs text-text-secondary truncate">
                                        {top.last_message || top.label || '—'}
                                    </div>
                                    {a.scopes.length > 1 && (
                                        <div className="text-[11px] text-text-tertiary">
                                            {a.scopes.length} conversations
                                        </div>
                                    )}
                                </div>
                            </button>
                        );
                    })}
                </div>
            </aside>

            {/* ── conversation pane ─────────────────────────────────────── */}
            <section className={`flex-1 min-w-0 md:flex flex-col bg-bg-panel ${mobilePane ? 'flex' : 'hidden'}`}>
                {!sel ? (
                    <div className="flex-1 flex items-center justify-center text-text-tertiary text-sm">
                        Select a conversation
                    </div>
                ) : (
                    <>
                        <div className="px-4 h-[54px] flex-shrink-0 border-b border-border-subtle flex items-center gap-2.5">
                            <button
                                onClick={() => setMobilePane(false)}
                                className="md:hidden -ml-1 p-1 text-text-tertiary hover:text-text-primary flex-shrink-0"
                                title="Back to conversations"
                                aria-label="Back"
                            >
                                <ChevronLeft className="w-5 h-5" />
                            </button>
                            <div
                                className="w-7 h-7 rounded-lg flex items-center justify-center text-white text-xs font-bold flex-shrink-0"
                                style={{ background: agentColor(sel.agent_name) }}
                            >
                                {(sel.agent_name || '?').slice(0, 2).toUpperCase()}
                            </div>
                            <div className="text-sm font-semibold text-text-primary truncate">{sel.agent_name}</div>

                            {/* Per-agent conversation (scope) selector */}
                            <div className="relative ml-auto">
                                <button
                                    onClick={() => setScopeOpen((v) => !v)}
                                    className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-bg-hover border border-border-subtle min-w-[180px] text-left"
                                    title="Switch conversation"
                                >
                                    <span className="flex-1 text-xs font-medium text-text-primary truncate">
                                        {sel.label || 'Conversation'}
                                    </span>
                                    <ChevronDown className="w-3 h-3 text-text-tertiary flex-shrink-0" />
                                </button>
                                {scopeOpen && (
                                    <>
                                        <div className="fixed inset-0 z-30" onClick={() => setScopeOpen(false)} />
                                        <div className="absolute right-0 top-full mt-1 z-40 w-64 rounded-lg border border-border-subtle bg-bg-app shadow-xl p-1">
                                            <div className="px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-text-tertiary">
                                                Conversations
                                            </div>
                                            {selScopes.map((c) => (
                                                <button
                                                    key={c.scope_key}
                                                    onClick={() => pickScope(c)}
                                                    className="w-full flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-bg-hover text-left"
                                                >
                                                    <span className="flex-1 min-w-0">
                                                        <span className="block text-xs text-text-primary truncate">{c.label}</span>
                                                        {c.last_message && (
                                                            <span className="block text-[10px] text-text-tertiary truncate">
                                                                {c.last_message}
                                                            </span>
                                                        )}
                                                    </span>
                                                    {c.scope_key === sel.scope_key && (
                                                        <Check className="w-3.5 h-3.5 text-accent-primary flex-shrink-0" />
                                                    )}
                                                </button>
                                            ))}
                                        </div>
                                    </>
                                )}
                            </div>
                        </div>

                        <div
                            ref={containerRef}
                            onScroll={onScroll}
                            className="flex-1 overflow-y-auto px-4 py-4 space-y-2"
                        >
                            {!reachedStartRef.current && serverLoadedCount(messages) > 0 && (
                                <div className="text-[11px] text-text-tertiary text-center py-1">
                                    Scroll up for older messages…
                                </div>
                            )}
                            {messages.length === 0 && (
                                <div className="text-sm text-text-secondary text-center py-8">
                                    No messages yet. Say hello.
                                </div>
                            )}
                            {messages.map((m) => <ChatBubble key={m.id} m={m} onAnswer={postMessage} />)}
                            {working && (
                                <div className="flex items-center gap-1.5 px-2 text-xs text-text-tertiary">
                                    <Loader className="w-3 h-3 animate-spin" />
                                    {sel.agent_name || 'Agent'} is thinking…
                                </div>
                            )}
                            <div ref={bottomRef} />
                        </div>

                        <div className="p-3 border-t border-border-subtle">
                            <div className="flex items-end gap-2">
                                <textarea
                                    ref={inputRef}
                                    rows={1}
                                    value={input}
                                    onChange={(e) => setInput(e.target.value)}
                                    onKeyDown={(e) => {
                                        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
                                    }}
                                    placeholder="Type a message…  (Shift+Enter for a new line)"
                                    className="flex-1 resize-none bg-bg-hover border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-primary max-h-44 overflow-y-auto"
                                />
                                {working ? (
                                    <button onClick={stop} className="p-2 rounded-lg bg-red-500/15 text-red-400 hover:bg-red-500/25" title="Stop">
                                        <Ban className="w-4 h-4" />
                                    </button>
                                ) : (
                                    <button
                                        onClick={send}
                                        disabled={!input.trim() || sending}
                                        className="p-2 rounded-lg bg-accent-primary text-white disabled:opacity-40 hover:brightness-110"
                                        title="Send"
                                    >
                                        <Send className="w-4 h-4" />
                                    </button>
                                )}
                            </div>
                        </div>
                    </>
                )}
            </section>
        </div>
    );
}

// Shared with FloatingChat's bubble shape — kept local to avoid coupling the
// two surfaces.
function ChatBubble({ m, onAnswer }) {
    const role = m.role || 'assistant';
    if (role === 'system') {
        return <div className="text-[11px] text-text-tertiary text-center px-4 py-1">{m.content}</div>;
    }
    if (role === 'tool') {
        if (m.tool_name === 'AskUserQuestion') {
            return <AskUserQuestionCard toolInput={m.tool_input} onAnswer={onAnswer} />;
        }
        const label = m.tool_name ? `Used ${m.tool_name}` : (m.content || m.tool_output || 'tool');
        return <div className="text-[11px] text-text-tertiary px-2 font-mono truncate">{label}</div>;
    }
    const isUser = role === 'user';
    return (
        <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
            {/* Two quiet, distinct bubbles: the user's own message is a soft
                lavender tint with a lavender hairline (branded, not a glaring
                fill); agent replies sit on a neutral raised card. Light text on
                both for readable contrast. */}
            <div
                className={`max-w-[78%] rounded-xl border px-3.5 py-2 text-sm break-words ${isUser ? 'whitespace-pre-wrap' : ''}`}
                style={isUser
                    ? { background: 'var(--tint-lavender)', borderColor: 'rgba(201,184,255,0.40)', color: 'var(--text-primary)' }
                    : { background: 'var(--bg-card)', borderColor: 'var(--border-subtle)', color: 'var(--text-primary)' }}
            >
                {isUser
                    ? (m.content || '…')
                    : (m.content ? <Markdown className="chat-md text-text-primary">{m.content}</Markdown> : '…')}
            </div>
        </div>
    );
}

export default Chat;
