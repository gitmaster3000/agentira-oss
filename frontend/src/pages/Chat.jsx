import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
    Send, Loader, MessageSquare, ChevronDown, ChevronLeft, Check, Plus, Square,
} from 'lucide-react';
import { api } from '../api';
import { AskUserQuestionCard } from '../components/AskUserQuestionCard';
import { Markdown } from '../components/Markdown';
import { mergeWindow, serverLoadedCount } from '../lib/chatPagination';

// Global Chat page (design §2.4): the left rail lists one row per AGENT (not one
// row per conversation). Picking an agent opens its most-recent thread; the
// per-agent "Conversation" selector at the top of the pane switches between
// that agent's scoped chats (General / project / task). Same slash commands
// and New Chat flow as AgentDetail chat (AP-436).
const POLL_MS = 3000;
const PAGE_SIZE = 50;
const PREFETCH_PX = 120;
// Composer grows with typed lines, then stops and scrolls inside (px ≈ 11 lines).
const COMPOSER_MAX_H = 176;
// Dropdown menus scroll inside this cap so a long list never grows the page.
const DROPDOWN_MAX_H = 'min(360px, 70vh)';

const SLASH_COMMANDS = [
    { name: '/context', desc: 'Show what context (project, MCP, env, prompts) will be sent on the next message' },
    { name: '/clear', desc: "Wipe the agent's memory for this chat (run history and diffs are kept)" },
];

function relTime(iso) {
    if (!iso) return '';
    const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 60) return 'now';
    if (s < 3600) return `${Math.floor(s / 60)}m`;
    if (s < 86400) return `${Math.floor(s / 3600)}h`;
    return `${Math.floor(s / 86400)}d`;
}

function agentColor(name) {
    let h = 0;
    for (let i = 0; i < (name || '').length; i++) h = (h * 31 + name.charCodeAt(i)) % 360;
    return `hsl(${h} 55% 55%)`;
}

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

function projectIdFromScope(scopeKey) {
    if (!scopeKey || !scopeKey.startsWith('chat:project:')) return null;
    return scopeKey.slice('chat:project:'.length) || null;
}

function freshScopeKey(existingKeys) {
    const keys = existingKeys instanceof Set ? existingKeys : new Set(existingKeys || []);
    if (!keys.has('chat:default')) return 'chat:default';
    return `chat:user:${Math.random().toString(36).slice(2, 10)}`;
}

function scopeLabel(scopeKey) {
    if (!scopeKey || scopeKey === 'chat:default') return 'General';
    if (scopeKey.startsWith('chat:project:')) return 'Project chat';
    if (scopeKey.startsWith('chat:user:')) return 'New chat';
    if (scopeKey.startsWith('task:')) return 'Task chat';
    return 'Conversation';
}

// AP-509: `/chat?agent=<id>&scope=<scope_key>` opens that conversation directly
// (a "needs input" notification / Needs-you card lands on the agent's question).
function selFromUrl() {
    const q = new URLSearchParams(window.location.search);
    const agent_id = q.get('agent');
    const scope_key = q.get('scope');
    return agent_id && scope_key ? { agent_id, scope_key, agent_name: '', label: '' } : null;
}

export function Chat() {
    const [convos, setConvos] = useState([]);
    const [convosLoading, setConvosLoading] = useState(true);
    const [sel, setSel] = useState(selFromUrl);    // {agent_id, scope_key, agent_name, label}
    const [scopeOpen, setScopeOpen] = useState(false);
    const [newChatOpen, setNewChatOpen] = useState(false);
    const [roster, setRoster] = useState([]);       // agents for New chat picker
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [inputFocused, setInputFocused] = useState(false);
    const [sending, setSending] = useState(false);
    const [stopped, setStopped] = useState(false);
    const [scopeLive, setScopeLive] = useState(false);
    const [mobilePane, setMobilePane] = useState(false);

    const bottomRef = useRef(null);
    const inputRef = useRef(null);
    const containerRef = useRef(null);
    const messagesRef = useRef([]);
    const loadingOlderRef = useRef(false);
    const reachedStartRef = useRef(false);
    const lastIdRef = useRef(null);

    const loadConvos = useCallback(async () => {
        try {
            const data = await api.forge.listChats();
            if (Array.isArray(data)) {
                setConvos(data);
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

    // Roster for New chat — all workspace agents, not only ones with threads.
    useEffect(() => {
        api.forge.listAgents()
            .then((list) => { if (Array.isArray(list)) setRoster(list); })
            .catch(() => {});
    }, []);

    // A deep-linked conversation arrives without a name — fill it from the
    // conversation list or the roster once either has loaded.
    useEffect(() => {
        if (!sel || sel.agent_name) return;
        const c = convos.find((x) => x.agent_id === sel.agent_id && x.scope_key === sel.scope_key);
        const name = c?.agent_name || roster.find((a) => a.id === sel.agent_id)?.name;
        if (name) setSel((cur) => (cur && !cur.agent_name ? { ...cur, agent_name: name, label: c?.label || cur.label } : cur));
    }, [sel, convos, roster]);

    useEffect(() => { messagesRef.current = messages; }, [messages]);

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

    const selKey = sel ? `${sel.agent_id}|${sel.scope_key}` : null;
    const lastUserIdx = messages.map((m) => m.role).lastIndexOf('user');
    useEffect(() => {
        if (!sel) return;
        setMessages([]);
        setStopped(false);
        reachedStartRef.current = false;
        loadingOlderRef.current = false;
        loadMessages();
        const t = setInterval(loadMessages, POLL_MS);
        return () => clearInterval(t);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [selKey]);

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

    // Auto-grow the message field with content, up to COMPOSER_MAX_H, then
    // enable internal scroll (hidden until the cap so no idle scrollbar chrome).
    useEffect(() => {
        const el = inputRef.current;
        if (!el) return;
        el.style.height = 'auto';
        const contentH = el.scrollHeight;
        el.style.height = `${Math.min(contentH, COMPOSER_MAX_H)}px`;
        el.style.overflowY = contentH > COMPOSER_MAX_H ? 'auto' : 'hidden';
    }, [input, selKey]);

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
            const project_id = projectIdFromScope(sel.scope_key);
            await api.forge.sendRuntimeChat(sel.agent_id, {
                content: text,
                scope_key: sel.scope_key,
                user_context: {
                    surface: 'chat_page',
                    route: window.location.pathname,
                    ...(project_id ? { project_id } : {}),
                },
            });
            setMessages((prev) => prev.filter((m) => m.id !== localId));
            await loadMessages();
            loadConvos();
        } catch (err) {
            console.error('Chat send failed:', err);
        } finally {
            setSending(false);
            inputRef.current?.focus();
        }
    };

    // ADR 008 / AP-93 slash commands + normal send (parity with AgentDetail).
    const handleSend = async () => {
        if (!input.trim() || sending || !sel) return;
        const trimmed = input.trim();

        if (trimmed === '/clear') {
            setInput('');
            if (!window.confirm(
                `Clear ${sel.label || scopeLabel(sel.scope_key)}? This wipes the agent's memory of this chat. Run history and diffs are kept.`,
            )) {
                inputRef.current?.focus();
                return;
            }
            try {
                await api.forge.clearConversation(sel.agent_id, sel.scope_key);
                setMessages([]);
                await loadConvos();
            } catch (err) {
                setMessages((prev) => [...prev, {
                    id: `local-clear-${Date.now()}`,
                    role: 'system',
                    content: `Clear failed: ${err.message || err}`,
                    created_at: new Date().toISOString(),
                }]);
            }
            inputRef.current?.focus();
            return;
        }

        if (trimmed === '/context' || trimmed.startsWith('/context ')) {
            setInput('');
            inputRef.current?.focus();
            const project_id = projectIdFromScope(sel.scope_key);
            try {
                const preview = await api.forge.getDispatchPreview(sel.agent_id, project_id);
                setMessages((prev) => [
                    ...prev,
                    {
                        id: `local-context-${Date.now()}`,
                        role: 'system',
                        content: '',
                        preview: { ...preview, ctx: { project_id, surface: 'chat_page' } },
                        created_at: new Date().toISOString(),
                    },
                ]);
            } catch (err) {
                setMessages((prev) => [
                    ...prev,
                    {
                        id: `local-context-${Date.now()}`,
                        role: 'system',
                        content: `Could not load dispatch preview: ${err.message || err}`,
                        created_at: new Date().toISOString(),
                    },
                ]);
            }
            return;
        }

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

    const _last = messages[messages.length - 1];
    const lastIsUser = !!_last && _last.role === 'user' && _last.created_at
        && (Date.now() - new Date(_last.created_at).getTime()) < 10 * 60 * 1000;
    const working = !stopped && (scopeLive || lastIsUser);

    const { agents, byId } = groupByAgent(convos);
    const selScopes = (sel && byId.get(sel.agent_id)?.scopes) || [];

    const pickAgent = (a) => {
        const top = a.scopes[0];
        setScopeOpen(false);
        setNewChatOpen(false);
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

    // Start a brand-new general thread for an agent (sidebar New chat).
    const startNewChat = (agent) => {
        const agentId = agent.id || agent.agent_id;
        const agentName = agent.name || agent.agent_name || 'Agent';
        const existing = (byId.get(agentId)?.scopes || []).map((c) => c.scope_key);
        const scope_key = freshScopeKey(existing);
        setNewChatOpen(false);
        setScopeOpen(false);
        setMobilePane(true);
        setSel({
            agent_id: agentId,
            scope_key,
            agent_name: agentName,
            label: scopeLabel(scope_key),
        });
    };

    // Also expose New chat for the currently selected agent in the scope menu.
    const startNewChatForSelected = () => {
        if (!sel) return;
        const existing = selScopes.map((c) => c.scope_key);
        const scope_key = freshScopeKey(existing);
        setScopeOpen(false);
        setSel({
            agent_id: sel.agent_id,
            scope_key,
            agent_name: sel.agent_name,
            label: scopeLabel(scope_key),
        });
    };

    // Agents shown in New chat: roster if loaded, else agents already on the rail.
    const newChatAgents = roster.length > 0
        ? roster
        : agents.map((a) => ({ id: a.agent_id, name: a.agent_name }));

    return (
        <div className="flex h-full min-h-0 overflow-hidden">
            {/* ── agent list (one row per agent) ────────────────────────── */}
            <aside className={`w-full md:w-72 flex-shrink-0 border-r border-border-subtle bg-bg-panel md:flex flex-col min-h-0 ${mobilePane ? 'hidden' : 'flex'}`}>
                <div className="px-4 h-[54px] flex-shrink-0 border-b border-border-subtle flex items-center gap-2">
                    <MessageSquare className="w-5 h-5 text-accent-primary" />
                    <span className="text-title-sm font-bold text-text-primary">Chat</span>
                    <span className="ml-auto text-[11px] text-text-tertiary">{agents.length} agents</span>
                    <div className="relative">
                        <button
                            type="button"
                            onClick={() => setNewChatOpen((v) => !v)}
                            className="btn btn-ghost p-1.5 rounded-lg"
                            title="New chat"
                            aria-label="New chat"
                        >
                            <Plus className="w-4 h-4" />
                        </button>
                        {newChatOpen && (
                            <>
                                <div className="fixed inset-0 z-30" onClick={() => setNewChatOpen(false)} />
                                <div
                                    className="absolute right-0 top-full mt-1 z-40 w-64 rounded-lg border border-border-subtle bg-bg-app shadow-xl flex flex-col overflow-hidden"
                                    style={{ maxHeight: DROPDOWN_MAX_H }}
                                    data-testid="new-chat-dropdown"
                                >
                                    <div className="px-2 py-1.5 text-[10px] font-bold uppercase tracking-wider text-text-tertiary flex-shrink-0">
                                        New chat with
                                    </div>
                                    <div className="overflow-y-auto min-h-0 overscroll-contain p-1 pt-0">
                                        {newChatAgents.length === 0 ? (
                                            <div className="px-2 py-3 text-xs text-text-tertiary">
                                                No agents available yet.
                                            </div>
                                        ) : (
                                            newChatAgents.map((a) => {
                                                const id = a.id || a.agent_id;
                                                const name = a.name || a.agent_name || 'Agent';
                                                return (
                                                    <button
                                                        key={id}
                                                        type="button"
                                                        onClick={() => startNewChat(a)}
                                                        className="w-full flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-bg-hover text-left"
                                                    >
                                                        <div
                                                            className="w-6 h-6 rounded-md flex items-center justify-center text-white text-[10px] font-bold flex-shrink-0"
                                                            style={{ background: agentColor(name) }}
                                                        >
                                                            {name.slice(0, 2).toUpperCase()}
                                                        </div>
                                                        <span className="text-xs text-text-primary truncate">{name}</span>
                                                    </button>
                                                );
                                            })
                                        )}
                                    </div>
                                </div>
                            </>
                        )}
                    </div>
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
                            No conversations yet. Use <strong className="text-text-secondary">+</strong> to start one.
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
            <section className={`flex-1 min-w-0 min-h-0 md:flex flex-col bg-bg-panel overflow-hidden ${mobilePane ? 'flex' : 'hidden'}`}>
                {!sel ? (
                    <div className="flex-1 flex items-center justify-center text-text-tertiary text-sm">
                        Select a conversation, or start a new one with +
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
                            <div className="text-sm font-semibold text-text-primary truncate">{sel.agent_name || 'Agent'}</div>

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
                                        <div
                                            className="absolute right-0 top-full mt-1 z-40 w-64 rounded-lg border border-border-subtle bg-bg-app shadow-xl flex flex-col overflow-hidden"
                                            style={{ maxHeight: DROPDOWN_MAX_H }}
                                            data-testid="conversations-dropdown"
                                        >
                                            <div className="px-2 py-1.5 text-[10px] font-bold uppercase tracking-wider text-text-tertiary flex-shrink-0">
                                                Conversations
                                            </div>
                                            <div className="overflow-y-auto min-h-0 overscroll-contain p-1 pt-0">
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
                                                {/* Optimistic: selected scope not yet in list (fresh New chat) */}
                                                {sel && !selScopes.some((c) => c.scope_key === sel.scope_key) && (
                                                    <button
                                                        type="button"
                                                        className="w-full flex items-center gap-2 px-2 py-1.5 rounded-md bg-bg-hover text-left"
                                                    >
                                                        <span className="flex-1 min-w-0">
                                                            <span className="block text-xs text-text-primary truncate">
                                                                {sel.label || scopeLabel(sel.scope_key)}
                                                            </span>
                                                        </span>
                                                        <Check className="w-3.5 h-3.5 text-accent-primary flex-shrink-0" />
                                                    </button>
                                                )}
                                            </div>
                                            <div className="border-t border-border-subtle p-1 flex-shrink-0">
                                                <button
                                                    type="button"
                                                    onClick={startNewChatForSelected}
                                                    className="w-full flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-bg-hover text-left"
                                                >
                                                    <Plus className="w-3.5 h-3.5 text-accent-primary" />
                                                    <span className="text-xs font-medium text-text-primary">New chat</span>
                                                </button>
                                            </div>
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
                                    No messages yet. Say hello — or type / for commands.
                                </div>
                            )}
                            {messages.map((m, i) => (
                                // A question stays clickable only until the human replies after it.
                                <ChatBubble key={m.id} m={m} onAnswer={i > lastUserIdx ? postMessage : undefined} />
                            ))}
                            {working && (
                                <div className="flex items-center gap-1.5 px-2 text-xs text-text-tertiary">
                                    <Loader className="w-3 h-3 animate-spin" />
                                    {sel.agent_name || 'Agent'} is thinking…
                                </div>
                            )}
                            <div ref={bottomRef} />
                        </div>

                        {/* Composer — themed .input + .btn; textarea auto-grows to a cap */}
                        <div className="px-4 py-3 border-t border-border-subtle bg-bg-panel relative">
                            {inputFocused && (
                                <SlashCommandSuggest
                                    input={input}
                                    onPick={(cmd) => {
                                        setInput(`${cmd} `);
                                        inputRef.current?.focus();
                                    }}
                                />
                            )}
                            <div className="flex items-end gap-2">
                                <div
                                    className="input flex-1 flex items-end cursor-text !py-2.5"
                                    onClick={() => inputRef.current?.focus()}
                                >
                                    <textarea
                                        ref={inputRef}
                                        rows={1}
                                        className="flex-1 w-full bg-transparent border-0 outline-none resize-none text-sm text-text-primary placeholder:text-text-tertiary min-w-0 leading-5"
                                        style={{ maxHeight: COMPOSER_MAX_H, overflowY: 'hidden' }}
                                        placeholder="Send a message — / for commands  (Shift+Enter for new line)"
                                        value={input}
                                        onChange={(e) => setInput(e.target.value)}
                                        onKeyDown={(e) => {
                                            if (e.key === 'Enter' && !e.shiftKey) {
                                                e.preventDefault();
                                                handleSend();
                                            }
                                        }}
                                        onFocus={() => setInputFocused(true)}
                                        onBlur={() => setInputFocused(false)}
                                        disabled={sending}
                                    />
                                </div>
                                {working ? (
                                    <button
                                        type="button"
                                        onClick={stop}
                                        className="btn btn-ghost py-2.5 text-red-400 hover:text-red-500 hover:bg-red-500/10"
                                        title="Stop"
                                    >
                                        <Square className="w-4 h-4" />
                                    </button>
                                ) : (
                                    <button
                                        type="button"
                                        onClick={handleSend}
                                        disabled={!input.trim() || sending}
                                        className="btn btn-primary py-2.5 disabled:opacity-40"
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

function SlashCommandSuggest({ input, onPick }) {
    if (!input.startsWith('/')) return null;
    const query = input.slice(1).split(/\s/)[0].toLowerCase();
    const matches = SLASH_COMMANDS.filter((c) => c.name.slice(1).startsWith(query));
    if (matches.length === 0) return null;
    return (
        <div className="absolute bottom-full left-4 right-4 mb-1 z-20 rounded-xl border border-border-subtle bg-bg-panel shadow-lg overflow-hidden max-w-md">
            <div className="text-[10px] uppercase tracking-wider text-text-tertiary px-3 py-1.5 bg-bg-hover/50">
                Slash commands
            </div>
            {matches.map((cmd) => (
                <button
                    key={cmd.name}
                    type="button"
                    onMouseDown={(e) => { e.preventDefault(); onPick(cmd.name); }}
                    className="w-full text-left px-3 py-2 hover:bg-bg-hover flex items-center gap-3 transition-colors"
                >
                    <code className="text-sm text-accent-primary font-mono">{cmd.name}</code>
                    <span className="text-xs text-text-tertiary truncate">{cmd.desc}</span>
                </button>
            ))}
        </div>
    );
}

function ChatBubble({ m, onAnswer }) {
    const role = m.role || 'assistant';
    if (m.preview) {
        return (
            <div
                className="rounded-xl border px-3.5 py-3 text-sm"
                style={{ background: 'var(--bg-card)', borderColor: 'var(--border-subtle)' }}
            >
                <ContextPreviewCard preview={m.preview} />
            </div>
        );
    }
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

function ContextPreviewCard({ preview }) {
    const p = preview || {};
    const proj = p.project || {};
    const ag = p.agent || {};
    const env = p.env_vars || {};
    const sp = p.system_prompt_addenda || {};
    return (
        <div className="text-sm">
            <div className="text-xs text-text-tertiary mb-3 flex items-center gap-2">
                <span className="font-mono px-1.5 py-0.5 rounded bg-bg-hover">/context</span>
                <span>for @{ag.name || '—'}</span>
            </div>
            <div className="mb-3">
                <div className="text-[10px] uppercase tracking-wider text-text-tertiary mb-1.5">Project</div>
                {proj.id ? (
                    <div className="text-sm text-text-primary">{proj.name || proj.id}</div>
                ) : (
                    <div className="text-xs text-text-tertiary italic">— none. Chat runs without a project cwd.</div>
                )}
            </div>
            <div className="mb-3">
                <div className="text-[10px] uppercase tracking-wider text-text-tertiary mb-1.5">Runtime</div>
                <div className="flex flex-wrap gap-2 text-xs">
                    <span className="px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400">{ag.runtime_provider || '—'}</span>
                    <span className="text-text-secondary">{ag.model || '—'}</span>
                </div>
            </div>
            <div className="mb-1">
                <div className="text-[10px] uppercase tracking-wider text-text-tertiary mb-1.5">MCP servers</div>
                {p.mcp_servers?.length ? (
                    <div className="flex flex-wrap gap-1.5">
                        {p.mcp_servers.map((s) => (
                            <span key={s} className="px-2 py-0.5 rounded bg-accent-subtle text-accent-primary text-xs font-mono">{s}</span>
                        ))}
                    </div>
                ) : (
                    <div className="text-xs text-text-tertiary italic">— none</div>
                )}
            </div>
            {env.injected_by_daemon?.length > 0 && (
                <div className="mt-3 text-[11px] text-text-tertiary">
                    Daemon injects: {env.injected_by_daemon.join(', ')}
                </div>
            )}
            {sp && Object.keys(sp).length > 0 && null}
        </div>
    );
}

export default Chat;
