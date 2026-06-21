import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Sparkles, Send, Loader, Ban, MessageSquare } from 'lucide-react';
import { api } from '../api';
import { AskUserQuestionCard } from '../components/AskUserQuestionCard';
import { Markdown } from '../components/Markdown';
import { mergeWindow, serverLoadedCount } from '../lib/chatPagination';

// Global Chat page (design §2.4): left conversation list across every agent
// (GET /forge/chats), right conversation pane. Reuses the FloatingChat message
// loading/sending logic but scopes to the picked (agent_id, scope_key) instead
// of the single chat:default thread.
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

export function Chat() {
    const [convos, setConvos] = useState([]);
    const [sel, setSel] = useState(null);          // {agent_id, scope_key, agent_name, label}
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [sending, setSending] = useState(false);
    const [stopped, setStopped] = useState(false);

    const bottomRef = useRef(null);
    const inputRef = useRef(null);
    const containerRef = useRef(null);
    const messagesRef = useRef([]);
    const loadingOlderRef = useRef(false);
    const reachedStartRef = useRef(false);
    const lastIdRef = useRef(null);

    // ── conversation list (across all agents) ───────────────────────────
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
        reachedStartRef.current = false;
        loadingOlderRef.current = false;
        loadMessages();
        const t = setInterval(loadMessages, POLL_MS);
        return () => clearInterval(t);
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

    const _last = messages[messages.length - 1];
    const lastIsUser = !stopped && !!_last && _last.role === 'user' && _last.created_at
        && (Date.now() - new Date(_last.created_at).getTime()) < 10 * 60 * 1000;

    return (
        <div className="flex h-full min-h-0">
            {/* ── conversation list ─────────────────────────────────────── */}
            <aside className="w-72 flex-shrink-0 border-r border-border-subtle bg-bg-panel flex flex-col">
                <div className="px-4 h-[54px] flex-shrink-0 border-b border-border-subtle flex items-center gap-2">
                    <MessageSquare className="w-5 h-5 text-accent-primary" />
                    <span className="text-title-sm font-bold text-text-primary">Chat</span>
                </div>
                <div className="flex-1 overflow-y-auto">
                    {convos.length === 0 && (
                        <div className="text-xs text-text-tertiary text-center py-8 px-4">
                            No conversations yet.
                        </div>
                    )}
                    {convos.map((c) => {
                        const active = sel && sel.agent_id === c.agent_id && sel.scope_key === c.scope_key;
                        return (
                            <button
                                key={`${c.agent_id}|${c.scope_key}`}
                                onClick={() => setSel({
                                    agent_id: c.agent_id, scope_key: c.scope_key,
                                    agent_name: c.agent_name, label: c.label,
                                })}
                                className={`w-full text-left px-3 py-2.5 border-b border-border-subtle flex gap-2.5
                                    ${active ? 'bg-accent-subtle' : 'hover:bg-bg-hover'}`}
                            >
                                <div
                                    className="w-8 h-8 rounded-lg flex-shrink-0 flex items-center justify-center text-white text-xs font-bold"
                                    style={{ background: agentColor(c.agent_name) }}
                                >
                                    {(c.agent_name || '?').slice(0, 2).toUpperCase()}
                                </div>
                                <div className="min-w-0 flex-1">
                                    <div className="flex items-center justify-between gap-2">
                                        <span className="text-sm font-medium text-text-primary truncate">
                                            {c.agent_name || 'Agent'}
                                        </span>
                                        <span className="text-[11px] text-text-tertiary flex-shrink-0">
                                            {relTime(c.last_used_at)}
                                        </span>
                                    </div>
                                    <div className="text-[11px] text-text-tertiary truncate">{c.label}</div>
                                    <div className="text-xs text-text-secondary truncate">
                                        {c.last_message || '—'}
                                    </div>
                                </div>
                            </button>
                        );
                    })}
                </div>
            </aside>

            {/* ── conversation pane ─────────────────────────────────────── */}
            <section className="flex-1 min-w-0 flex flex-col bg-bg-panel">
                {!sel ? (
                    <div className="flex-1 flex items-center justify-center text-text-tertiary text-sm">
                        Select a conversation
                    </div>
                ) : (
                    <>
                        <div className="px-4 h-[54px] flex-shrink-0 border-b border-border-subtle flex items-center gap-2.5">
                            <div
                                className="w-7 h-7 rounded-lg flex items-center justify-center text-white text-xs font-bold"
                                style={{ background: agentColor(sel.agent_name) }}
                            >
                                {(sel.agent_name || '?').slice(0, 2).toUpperCase()}
                            </div>
                            <div className="min-w-0">
                                <div className="text-sm font-semibold text-text-primary truncate">{sel.agent_name}</div>
                                <div className="text-[11px] text-text-tertiary truncate">{sel.label}</div>
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
                            {lastIsUser && (
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
                                    placeholder="Type a message…"
                                    className="flex-1 resize-none bg-bg-hover border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-primary max-h-28"
                                />
                                {lastIsUser ? (
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
            <div className={`max-w-[75%] rounded-lg px-3 py-2 text-sm break-words ${
                isUser ? 'bg-accent-primary text-white whitespace-pre-wrap' : 'bg-bg-hover text-text-primary'}`}>
                {isUser
                    ? (m.content || '…')
                    : (m.content ? <Markdown className="chat-md text-text-primary">{m.content}</Markdown> : '…')}
            </div>
        </div>
    );
}

export default Chat;
