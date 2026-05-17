import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Sparkles, X, Send, Loader } from 'lucide-react';
import { api } from '../api';

// The Concierge's conversation is a single workspace-wide thread.
const CONCIERGE_SCOPE = 'chat:default';
const POLL_MS = 3000;

/**
 * FloatingChat — the always-available Concierge assistant.
 *
 * A floating button (bottom-right) that opens a chat panel wired to the
 * system Concierge agent. Mounted on both Studio and Forge layouts so the
 * user can ask "how do I…" / "what is this" from anywhere.
 */
export function FloatingChat() {
    const [open, setOpen] = useState(false);
    const [conciergeId, setConciergeId] = useState(null);
    const [unavailable, setUnavailable] = useState(false);
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [sending, setSending] = useState(false);
    const bottomRef = useRef(null);
    const inputRef = useRef(null);

    // Resolve the Concierge agent the first time the panel opens.
    useEffect(() => {
        if (!open || conciergeId || unavailable) return;
        api.forge.getConcierge()
            .then((a) => setConciergeId(a.id))
            .catch(() => setUnavailable(true));
    }, [open, conciergeId, unavailable]);

    const loadMessages = useCallback(async () => {
        if (!conciergeId) return;
        try {
            const data = await api.forge.listMessages(conciergeId, {
                limit: 100, scope_key: CONCIERGE_SCOPE,
            });
            if (Array.isArray(data)) setMessages(data);
        } catch {
            // transient — keep what we have
        }
    }, [conciergeId]);

    // Poll messages while the panel is open.
    useEffect(() => {
        if (!open || !conciergeId) return;
        loadMessages();
        const t = setInterval(loadMessages, POLL_MS);
        return () => clearInterval(t);
    }, [open, conciergeId, loadMessages]);

    useEffect(() => {
        if (open) bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages.length, open]);

    useEffect(() => {
        if (open) inputRef.current?.focus();
    }, [open, conciergeId]);

    const send = async () => {
        const trimmed = input.trim();
        if (!trimmed || sending || !conciergeId) return;
        const localId = `local-${Date.now()}`;
        setMessages((prev) => [...prev, {
            id: localId, role: 'user', content: trimmed,
            created_at: new Date().toISOString(),
        }]);
        setInput('');
        setSending(true);
        try {
            await api.forge.sendRuntimeChat(conciergeId, {
                content: trimmed,
                scope_key: CONCIERGE_SCOPE,
                user_context: {
                    surface: 'floating_chat',
                    route: window.location.pathname,
                },
            });
            setMessages((prev) => prev.filter((m) => m.id !== localId));
            await loadMessages();
        } catch (err) {
            console.error('Concierge send failed:', err);
        } finally {
            setSending(false);
            inputRef.current?.focus();
        }
    };

    const lastIsUser = messages.length > 0
        && messages[messages.length - 1].role === 'user';

    if (!open) {
        return (
            <button
                onClick={() => setOpen(true)}
                className="fixed bottom-5 right-5 z-50 flex items-center gap-2 px-4 py-3 rounded-full bg-accent-primary text-white shadow-lg hover:brightness-110 transition-all"
                title="Ask the Concierge"
            >
                <Sparkles className="w-5 h-5" />
                <span className="text-sm font-medium">Ask Concierge</span>
            </button>
        );
    }

    return (
        <div className="fixed bottom-5 right-5 z-50 w-[380px] max-w-[calc(100vw-2rem)] h-[520px] max-h-[calc(100vh-3rem)] flex flex-col rounded-xl bg-bg-app border border-border-subtle shadow-2xl">
            {/* Header */}
            <div className="flex items-center gap-2 px-4 py-3 border-b border-border-subtle">
                <div className="w-7 h-7 rounded-lg bg-accent-subtle flex items-center justify-center">
                    <Sparkles className="w-4 h-4 text-accent-primary" />
                </div>
                <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-text-primary">Concierge</div>
                    <div className="text-xs text-text-tertiary">Your Agentira guide</div>
                </div>
                <button
                    onClick={() => setOpen(false)}
                    className="p-1 rounded hover:bg-bg-hover text-text-tertiary hover:text-text-primary"
                    title="Close"
                >
                    <X className="w-4 h-4" />
                </button>
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2">
                {unavailable && (
                    <div className="text-xs text-text-tertiary text-center py-6">
                        The Concierge isn't available right now.
                    </div>
                )}
                {!unavailable && messages.length === 0 && (
                    <div className="text-sm text-text-secondary text-center py-8 px-4">
                        Hi! I'm the Concierge. Ask me how anything in Agentira
                        works — projects, tasks, agents, runs — or what's on
                        your current screen.
                    </div>
                )}
                {messages.map((m) => <ChatBubble key={m.id} m={m} />)}
                {lastIsUser && (
                    <div className="flex items-center gap-1.5 px-2 text-xs text-text-tertiary">
                        <Loader className="w-3 h-3 animate-spin" />
                        Concierge is thinking…
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
                        placeholder={unavailable ? 'Concierge unavailable' : 'Ask the Concierge…'}
                        disabled={unavailable || !conciergeId}
                        className="flex-1 resize-none bg-bg-hover border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-primary disabled:opacity-50 max-h-28"
                    />
                    <button
                        onClick={send}
                        disabled={!input.trim() || sending || unavailable || !conciergeId}
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
