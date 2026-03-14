import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
    Bot, ArrowLeft, Wifi, WifiOff, Loader, Play, Clock, DollarSign,
    MessageSquare, Settings2, Activity, Webhook, Calendar, Send,
    ChevronDown, Eye, EyeOff, Zap, RefreshCw, ToggleLeft, ToggleRight,
    Terminal, User, Wrench, AlertCircle, CheckCircle, XCircle,
} from 'lucide-react';
import { api } from '../../api';

const STATUS_STYLES = {
    online:  { color: '#2ecc71', icon: Wifi, label: 'Online' },
    offline: { color: '#5f6368', icon: WifiOff, label: 'Offline' },
    busy:    { color: '#f1c40f', icon: Loader, label: 'Busy' },
};

const TABS = [
    { id: 'overview', label: 'Overview', icon: Activity },
    { id: 'chat', label: 'Chat', icon: MessageSquare },
    { id: 'runs', label: 'Runs', icon: Play },
    { id: 'config', label: 'Config', icon: Settings2 },
    { id: 'webhooks', label: 'Webhooks', icon: Webhook },
    { id: 'live', label: 'Live', icon: Eye },
];

export function AgentDetail() {
    const { agentId } = useParams();
    const [agent, setAgent] = useState(null);
    const [tab, setTab] = useState('overview');
    const [loading, setLoading] = useState(true);

    const loadAgent = useCallback(async () => {
        try {
            const data = await api.forge.getAgent(agentId);
            setAgent(data);
        } catch (err) {
            console.error('Failed to load agent:', err);
        } finally {
            setLoading(false);
        }
    }, [agentId]);

    useEffect(() => {
        loadAgent();
        const interval = setInterval(loadAgent, 8000);
        return () => clearInterval(interval);
    }, [loadAgent]);

    if (loading) {
        return <div className="flex-1 flex items-center justify-center text-text-tertiary">Loading agent...</div>;
    }
    if (!agent) {
        return <div className="flex-1 flex items-center justify-center text-text-tertiary">Agent not found</div>;
    }

    const status = STATUS_STYLES[agent.status] || STATUS_STYLES.offline;
    const StatusIcon = status.icon;

    return (
        <div className="flex-1 flex flex-col overflow-hidden">
            {/* Header */}
            <div className="px-6 pt-5 pb-0 space-y-4">
                <div className="flex items-center gap-3">
                    <Link to="/forge/agents" className="p-1.5 rounded-lg hover:bg-bg-hover text-text-tertiary hover:text-text-primary transition-colors">
                        <ArrowLeft className="w-4 h-4" />
                    </Link>
                    <div className="w-10 h-10 rounded-lg bg-bg-hover flex items-center justify-center">
                        <Bot className="w-5 h-5 text-text-secondary" />
                    </div>
                    <div className="flex-1">
                        <div className="flex items-center gap-2">
                            <h1 className="text-xl font-bold text-text-primary">{agent.name}</h1>
                            <span
                                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium"
                                style={{ backgroundColor: status.color + '20', color: status.color }}
                            >
                                <StatusIcon className="w-3 h-3" />
                                {status.label}
                            </span>
                        </div>
                        <div className="text-sm text-text-tertiary">
                            {agent.profile_name} &middot; {agent.executor_type} &middot; {agent.model || 'no model set'}
                        </div>
                    </div>
                    <div className="flex items-center gap-4 text-sm text-text-secondary">
                        <span className="flex items-center gap-1"><Play className="w-3.5 h-3.5" /> {agent.total_runs} runs</span>
                        <span className="flex items-center gap-1"><DollarSign className="w-3.5 h-3.5" /> ${agent.total_cost_usd.toFixed(4)}</span>
                    </div>
                </div>

                {/* Tabs */}
                <div className="flex gap-0 border-b border-border-subtle -mx-6 px-6">
                    {TABS.map((t) => (
                        <button
                            key={t.id}
                            onClick={() => setTab(t.id)}
                            className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                                tab === t.id
                                    ? 'border-accent-primary text-accent-primary'
                                    : 'border-transparent text-text-tertiary hover:text-text-secondary'
                            }`}
                        >
                            <t.icon className="w-4 h-4" />
                            {t.label}
                        </button>
                    ))}
                </div>
            </div>

            {/* Tab Content */}
            <div className="flex-1 overflow-auto">
                {tab === 'overview' && <OverviewTab agent={agent} />}
                {tab === 'chat' && <ChatTab agentId={agentId} />}
                {tab === 'runs' && <RunsTab agentId={agentId} />}
                {tab === 'config' && <ConfigTab agent={agent} onSaved={loadAgent} />}
                {tab === 'webhooks' && <WebhooksTab agentId={agentId} />}
                {tab === 'live' && <LiveTab agentId={agentId} agent={agent} />}
            </div>
        </div>
    );
}


// ── Overview Tab ────────────────────────────────────────────────────────

function OverviewTab({ agent }) {
    const [costs, setCosts] = useState(null);
    const [runtimeStatus, setRuntimeStatus] = useState(null);

    useEffect(() => {
        api.forge.getAgentCosts(agent.id).then(setCosts).catch(console.error);
        api.forge.getRuntimeStatus(agent.id).then(setRuntimeStatus).catch(console.error);
    }, [agent.id]);

    return (
        <div className="p-6 space-y-6">
            {/* Quick Stats */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <StatCard icon={Play} label="Total Runs" value={agent.total_runs} color="#7c4dff" />
                <StatCard icon={DollarSign} label="Total Cost" value={`$${agent.total_cost_usd.toFixed(4)}`} color="#f1c40f" />
                <StatCard icon={Clock} label="Last Heartbeat" value={agent.last_heartbeat ? timeAgo(agent.last_heartbeat) : 'Never'} color="#00bcd4" />
                <StatCard
                    icon={Calendar}
                    label="Schedule"
                    value={agent.schedule_enabled ? `${agent.schedule_start} - ${agent.schedule_end}` : 'Disabled'}
                    sub={agent.schedule_enabled ? `${agent.schedule_tz} · ${agent.schedule_days}` : null}
                    color="#2ecc71"
                />
            </div>

            {/* OpenClaw Live Status */}
            <div className="card">
                <h3 className="text-sm font-semibold text-text-primary mb-3">OpenClaw Status</h3>
                {runtimeStatus?.error ? (
                    <div className="text-xs text-red-400">{runtimeStatus.error}</div>
                ) : (
                    <>
                        <div className="flex items-center gap-3 mb-3">
                            <div className={`w-3 h-3 rounded-full ${runtimeStatus?.online ? 'bg-emerald-500' : 'bg-red-500'}`} />
                            <span className="text-sm text-text-primary font-medium">
                                {runtimeStatus?.online ? 'Online' : 'No active sessions'}
                            </span>
                            {runtimeStatus?.model && (
                                <span className="px-2 py-0.5 rounded bg-bg-hover text-xs text-text-secondary">{runtimeStatus.model}</span>
                            )}
                            {runtimeStatus?.heartbeat_enabled && (
                                <span className="px-2 py-0.5 rounded bg-emerald-500/15 text-xs text-emerald-400">heartbeat</span>
                            )}
                        </div>
                        {runtimeStatus?.sessions?.length > 0 && (
                            <div className="space-y-1.5">
                                <div className="text-xs text-text-tertiary font-medium uppercase tracking-wider">Active Sessions</div>
                                {runtimeStatus.sessions.map((s, i) => (
                                    <div key={i} className="flex items-center justify-between px-3 py-2 rounded bg-bg-hover text-xs">
                                        <span className="text-text-primary font-mono">{s.key}</span>
                                        <div className="flex items-center gap-3 text-text-secondary">
                                            <span>{s.model}</span>
                                            <span>{(s.input_tokens + s.output_tokens).toLocaleString()} tok</span>
                                            <span className={s.percent_used > 80 ? 'text-red-400 font-medium' : ''}>
                                                {s.percent_used}% ctx
                                            </span>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                        {runtimeStatus?.total_input_tokens > 0 && (
                            <div className="flex gap-4 mt-3 pt-3 border-t border-border-subtle text-xs text-text-tertiary">
                                <span>Input: {runtimeStatus.total_input_tokens.toLocaleString()}</span>
                                <span>Output: {runtimeStatus.total_output_tokens.toLocaleString()}</span>
                            </div>
                        )}
                    </>
                )}
            </div>

            {/* Cost Breakdown */}
            {costs && Object.keys(costs.by_model).length > 0 && (
                <div className="card">
                    <h3 className="text-sm font-semibold text-text-primary mb-3">Cost Breakdown by Model</h3>
                    <div className="space-y-2">
                        {Object.entries(costs.by_model).map(([model, data]) => (
                            <div key={model} className="flex items-center justify-between px-3 py-2 rounded-md bg-bg-hover text-sm">
                                <div>
                                    <span className="text-text-primary font-medium">{model}</span>
                                    <span className="text-text-tertiary ml-2">{data.runs} runs</span>
                                </div>
                                <div className="flex items-center gap-4 text-text-secondary">
                                    <span>{(data.input_tokens + data.output_tokens).toLocaleString()} tokens</span>
                                    <span className="font-medium">${data.cost_usd.toFixed(4)}</span>
                                </div>
                            </div>
                        ))}
                    </div>
                    <div className="flex justify-end mt-3 pt-3 border-t border-border-subtle text-sm">
                        <span className="text-text-secondary">Total: </span>
                        <span className="text-text-primary font-bold ml-1">${costs.total_cost_usd.toFixed(4)}</span>
                    </div>
                </div>
            )}

            {/* Config Summary */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="card">
                    <h3 className="text-sm font-semibold text-text-primary mb-2">System Prompt</h3>
                    <pre className="text-xs text-text-secondary whitespace-pre-wrap max-h-40 overflow-auto bg-bg-hover rounded p-3">
                        {agent.system_prompt || '(not set)'}
                    </pre>
                </div>
                <div className="card">
                    <h3 className="text-sm font-semibold text-text-primary mb-2">Personality</h3>
                    <pre className="text-xs text-text-secondary whitespace-pre-wrap max-h-40 overflow-auto bg-bg-hover rounded p-3">
                        {agent.personality || '(not set)'}
                    </pre>
                </div>
            </div>
        </div>
    );
}


// ── Chat Tab ───────────────────────────────────────────────────────────

function ChatTab({ agentId }) {
    const [messages, setMessages] = useState([]);
    const [loading, setLoading] = useState(true);
    const [autoScroll, setAutoScroll] = useState(true);
    const [input, setInput] = useState('');
    const [sending, setSending] = useState(false);
    const bottomRef = useRef(null);
    const containerRef = useRef(null);
    const inputRef = useRef(null);

    const msgCountRef = useRef(0);

    const loadMessages = useCallback(async () => {
        try {
            const data = await api.forge.listMessages(agentId, { limit: 200 });
            setMessages(data);
        } catch (err) {
            console.error('Failed to load messages:', err);
        } finally {
            setLoading(false);
        }
    }, [agentId]);

    useEffect(() => {
        loadMessages();
        const interval = setInterval(loadMessages, 3000);
        return () => clearInterval(interval);
    }, [loadMessages]);

    useEffect(() => {
        // Only auto-scroll when new messages arrive, not on every poll
        if (autoScroll && bottomRef.current && messages.length !== msgCountRef.current) {
            bottomRef.current.scrollIntoView({ behavior: 'smooth' });
        }
        msgCountRef.current = messages.length;
    }, [messages.length, autoScroll]);

    const handleSend = async () => {
        if (!input.trim() || sending) return;
        setSending(true);
        try {
            await api.forge.sendRuntimeChat(agentId, { content: input.trim() });
            setInput('');
            await loadMessages();
        } catch (err) {
            console.error('Send failed:', err);
        } finally {
            setSending(false);
            inputRef.current?.focus();
        }
    };

    if (loading) return <div className="flex-1 flex items-center justify-center text-text-tertiary p-6">Loading chat...</div>;

    const ROLE_STYLES = {
        system:    { bg: 'bg-purple-500/10', border: 'border-purple-500/20', icon: Terminal, label: 'System', color: '#a855f7' },
        user:      { bg: 'bg-blue-500/10',   border: 'border-blue-500/20',   icon: Send,     label: 'Sent',   color: '#3b82f6' },
        assistant: { bg: 'bg-emerald-500/10', border: 'border-emerald-500/20', icon: Bot,     label: 'Agent',  color: '#10b981' },
        tool:      { bg: 'bg-orange-500/10',  border: 'border-orange-500/20',  icon: Wrench,  label: 'Tool',   color: '#f97316' },
    };

    return (
        <div className="flex flex-col h-full">
            {/* Toolbar */}
            <div className="flex items-center justify-between px-6 py-2 border-b border-border-subtle bg-bg-panel">
                <span className="text-sm text-text-secondary">{messages.length} messages</span>
                <div className="flex items-center gap-2">
                    <button onClick={loadMessages} className="btn btn-ghost py-1 px-2 text-xs">
                        <RefreshCw className="w-3 h-3" /> Refresh
                    </button>
                    <button
                        onClick={() => setAutoScroll(!autoScroll)}
                        className={`btn btn-ghost py-1 px-2 text-xs ${autoScroll ? 'text-accent-primary' : ''}`}
                    >
                        {autoScroll ? <ToggleRight className="w-3 h-3" /> : <ToggleLeft className="w-3 h-3" />}
                        Auto-scroll
                    </button>
                </div>
            </div>

            {/* Messages */}
            <div ref={containerRef} className="flex-1 overflow-auto p-6 space-y-3">
                {messages.length === 0 ? (
                    <div className="text-center py-16 text-text-tertiary">
                        <MessageSquare className="w-10 h-10 mx-auto mb-3 opacity-40" />
                        <p>No messages yet. Messages will appear when the agent starts communicating.</p>
                    </div>
                ) : (
                    messages.map((msg) => {
                        const style = ROLE_STYLES[msg.role] || ROLE_STYLES.user;
                        const RoleIcon = style.icon;
                        return (
                            <div key={msg.id} className={`rounded-lg border ${style.bg} ${style.border} p-4`}>
                                <div className="flex items-center gap-2 mb-2">
                                    <RoleIcon className="w-4 h-4" style={{ color: style.color }} />
                                    <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: style.color }}>
                                        {style.label}
                                    </span>
                                    {msg.model_used && (
                                        <span className="text-xs text-text-tertiary px-1.5 py-0.5 rounded bg-bg-hover">{msg.model_used}</span>
                                    )}
                                    {(msg.input_tokens > 0 || msg.output_tokens > 0) && (
                                        <span className="text-xs text-text-tertiary">
                                            {msg.input_tokens}in / {msg.output_tokens}out
                                        </span>
                                    )}
                                    {msg.cost_usd > 0 && (
                                        <span className="text-xs text-text-tertiary">${msg.cost_usd.toFixed(4)}</span>
                                    )}
                                    <span className="text-xs text-text-tertiary ml-auto">{formatTime(msg.created_at)}</span>
                                </div>
                                <pre className="text-sm text-text-primary whitespace-pre-wrap font-mono leading-relaxed">{msg.content}</pre>
                                {msg.tool_name && (
                                    <div className="mt-2 pt-2 border-t border-border-subtle">
                                        <div className="text-xs font-medium text-text-secondary mb-1">
                                            <Wrench className="w-3 h-3 inline mr-1" />{msg.tool_name}
                                        </div>
                                        {msg.tool_input && (
                                            <details className="text-xs">
                                                <summary className="text-text-tertiary cursor-pointer hover:text-text-secondary">Input</summary>
                                                <pre className="mt-1 p-2 bg-bg-hover rounded text-text-secondary overflow-auto max-h-32">{msg.tool_input}</pre>
                                            </details>
                                        )}
                                        {msg.tool_output && (
                                            <details className="text-xs mt-1">
                                                <summary className="text-text-tertiary cursor-pointer hover:text-text-secondary">Output</summary>
                                                <pre className="mt-1 p-2 bg-bg-hover rounded text-text-secondary overflow-auto max-h-32">{msg.tool_output}</pre>
                                            </details>
                                        )}
                                    </div>
                                )}
                            </div>
                        );
                    })
                )}
                <div ref={bottomRef} />
            </div>

            {/* Send bar */}
            <div className="px-6 py-3 border-t border-border-subtle bg-bg-panel flex items-center gap-2">
                <input
                    ref={inputRef}
                    className="input flex-1"
                    placeholder="Send a message to the agent via OpenClaw..."
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
                    disabled={sending}
                />
                <button onClick={handleSend} disabled={sending || !input.trim()} className="btn btn-primary py-2.5">
                    {sending ? <Loader className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                </button>
            </div>
        </div>
    );
}


// ── Runs Tab ───────────────────────────────────────────────────────────

function RunsTab({ agentId }) {
    const [runs, setRuns] = useState([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const load = async () => {
            try {
                const data = await api.forge.listRuns({ agent_id: agentId, limit: 50 });
                setRuns(data);
            } catch (err) {
                console.error(err);
            } finally {
                setLoading(false);
            }
        };
        load();
        const interval = setInterval(load, 8000);
        return () => clearInterval(interval);
    }, [agentId]);

    const RUN_STATUS = {
        pending:   { bg: '#5f6368', label: 'Pending', icon: Clock },
        running:   { bg: '#f1c40f', label: 'Running', icon: Loader },
        completed: { bg: '#2ecc71', label: 'Done', icon: CheckCircle },
        failed:    { bg: '#e74c3c', label: 'Failed', icon: XCircle },
        cancelled: { bg: '#9aa0a6', label: 'Cancelled', icon: AlertCircle },
    };

    if (loading) return <div className="flex-1 flex items-center justify-center text-text-tertiary p-6">Loading runs...</div>;

    return (
        <div className="p-6">
            {runs.length === 0 ? (
                <div className="text-center py-16 text-text-tertiary">
                    <Play className="w-10 h-10 mx-auto mb-3 opacity-40" />
                    <p>No runs for this agent yet.</p>
                </div>
            ) : (
                <div className="card p-0 overflow-hidden">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="border-b border-border-subtle text-text-tertiary text-xs uppercase">
                                <th className="text-left px-4 py-3 font-medium">Status</th>
                                <th className="text-left px-4 py-3 font-medium">Task</th>
                                <th className="text-left px-4 py-3 font-medium">Trigger</th>
                                <th className="text-left px-4 py-3 font-medium">Model</th>
                                <th className="text-right px-4 py-3 font-medium">Duration</th>
                                <th className="text-right px-4 py-3 font-medium">Tokens</th>
                                <th className="text-right px-4 py-3 font-medium">Cost</th>
                                <th className="text-right px-4 py-3 font-medium">Time</th>
                            </tr>
                        </thead>
                        <tbody>
                            {runs.map((run) => {
                                const s = RUN_STATUS[run.status] || RUN_STATUS.pending;
                                const total = (run.input_tokens || 0) + (run.output_tokens || 0);
                                return (
                                    <tr key={run.id} className="border-b border-border-subtle hover:bg-bg-hover transition-colors">
                                        <td className="px-4 py-3">
                                            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium text-white" style={{ backgroundColor: s.bg }}>
                                                {s.label}
                                            </span>
                                        </td>
                                        <td className="px-4 py-3 text-text-secondary truncate max-w-[200px]">{run.task_title || '—'}</td>
                                        <td className="px-4 py-3">
                                            {run.trigger_event ? (
                                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-bg-hover text-xs text-text-secondary">
                                                    <Zap className="w-3 h-3" />{run.trigger_event}
                                                </span>
                                            ) : '—'}
                                        </td>
                                        <td className="px-4 py-3 text-text-tertiary text-xs truncate max-w-[120px]">{run.model_used || '—'}</td>
                                        <td className="px-4 py-3 text-right text-text-secondary">{run.duration_ms != null ? formatDuration(run.duration_ms) : '—'}</td>
                                        <td className="px-4 py-3 text-right text-text-secondary">{total > 0 ? total.toLocaleString() : '—'}</td>
                                        <td className="px-4 py-3 text-right text-text-secondary">{run.cost_usd > 0 ? `$${run.cost_usd.toFixed(4)}` : '—'}</td>
                                        <td className="px-4 py-3 text-right text-text-tertiary text-xs">{timeAgo(run.created_at)}</td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
}


// ── Config Tab ─────────────────────────────────────────────────────────

function ConfigTab({ agent, onSaved }) {
    const [form, setForm] = useState({
        name: agent.name,
        model: agent.model,
        executor_type: agent.executor_type,
        webhook_url: agent.webhook_url,
        system_prompt: agent.system_prompt,
        personality: agent.personality,
        runtime_type: agent.runtime_type,
        runtime_url: agent.runtime_url,
        runtime_gateway_token: agent.runtime_gateway_token,
        runtime_hooks_token: agent.runtime_hooks_token,
        runtime_agent_name: agent.runtime_agent_name,
    });
    const [schedule, setSchedule] = useState({
        start: agent.schedule_start,
        end: agent.schedule_end,
        tz: agent.schedule_tz,
        days: agent.schedule_days,
        enabled: agent.schedule_enabled,
    });
    const [saving, setSaving] = useState(false);
    const [msg, setMsg] = useState('');
    const [showGwToken, setShowGwToken] = useState(false);
    const [showHooksToken, setShowHooksToken] = useState(false);

    const saveAgent = async () => {
        setSaving(true);
        try {
            await api.forge.updateAgent(agent.id, form);
            await api.forge.updateSchedule(agent.id, schedule);
            setMsg('Saved');
            onSaved();
            setTimeout(() => setMsg(''), 2000);
        } catch (err) {
            setMsg('Error: ' + err.message);
        } finally {
            setSaving(false);
        }
    };

    const DAY_OPTIONS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
    const activeDays = schedule.days.split(',').filter(Boolean);

    const toggleDay = (day) => {
        const newDays = activeDays.includes(day)
            ? activeDays.filter(d => d !== day)
            : [...activeDays, day];
        setSchedule({ ...schedule, days: newDays.join(',') });
    };

    return (
        <div className="p-6 space-y-6 max-w-3xl">
            {/* Basic */}
            <section className="card space-y-4">
                <h3 className="text-sm font-semibold text-text-primary">Basic Configuration</h3>
                <div className="grid grid-cols-2 gap-4">
                    <div>
                        <label className="block text-xs text-text-tertiary mb-1">Name</label>
                        <input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                    </div>
                    <div>
                        <label className="block text-xs text-text-tertiary mb-1">Model</label>
                        <input className="input" value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} />
                    </div>
                    <div>
                        <label className="block text-xs text-text-tertiary mb-1">Executor</label>
                        <select className="input" value={form.executor_type} onChange={(e) => setForm({ ...form, executor_type: e.target.value })}>
                            <option value="http">HTTP</option>
                            <option value="zeroclaw">ZeroClaw</option>
                            <option value="cli">CLI</option>
                        </select>
                    </div>
                    <div>
                        <label className="block text-xs text-text-tertiary mb-1">Webhook URL</label>
                        <input className="input" value={form.webhook_url} onChange={(e) => setForm({ ...form, webhook_url: e.target.value })} />
                    </div>
                </div>
            </section>

            {/* Runtime Connection */}
            <section className="card space-y-4">
                <h3 className="text-sm font-semibold text-text-primary">Runtime Connection</h3>
                <p className="text-xs text-text-tertiary">Connect to the OpenClaw (or other) gateway that runs this agent. Forge proxies through this to show real data.</p>
                <div className="grid grid-cols-2 gap-4">
                    <div>
                        <label className="block text-xs text-text-tertiary mb-1">Runtime Type</label>
                        <select className="input" value={form.runtime_type} onChange={(e) => setForm({ ...form, runtime_type: e.target.value })}>
                            <option value="openclaw">OpenClaw</option>
                            <option value="zeroclaw">ZeroClaw</option>
                            <option value="openai">OpenAI-compatible</option>
                        </select>
                    </div>
                    <div>
                        <label className="block text-xs text-text-tertiary mb-1">Agent Name (model routing)</label>
                        <input className="input" placeholder="e.g. architect, frontend" value={form.runtime_agent_name} onChange={(e) => setForm({ ...form, runtime_agent_name: e.target.value })} />
                    </div>
                    <div className="col-span-2">
                        <label className="block text-xs text-text-tertiary mb-1">Gateway URL</label>
                        <input className="input" placeholder="http://127.0.0.1:18789" value={form.runtime_url} onChange={(e) => setForm({ ...form, runtime_url: e.target.value })} />
                    </div>
                    <div>
                        <label className="block text-xs text-text-tertiary mb-1">Gateway Token</label>
                        <div className="relative">
                            <input className="input pr-9" type={showGwToken ? 'text' : 'password'} placeholder="For /v1/chat/completions + WS RPC" value={form.runtime_gateway_token} onChange={(e) => setForm({ ...form, runtime_gateway_token: e.target.value })} />
                            <button type="button" onClick={() => setShowGwToken(!showGwToken)} className="absolute right-2 top-1/2 -translate-y-1/2 text-text-tertiary hover:text-text-primary transition-colors">
                                {showGwToken ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                            </button>
                        </div>
                    </div>
                    <div>
                        <label className="block text-xs text-text-tertiary mb-1">Hooks Token</label>
                        <div className="relative">
                            <input className="input pr-9" type={showHooksToken ? 'text' : 'password'} placeholder="For /hooks/agent triggers" value={form.runtime_hooks_token} onChange={(e) => setForm({ ...form, runtime_hooks_token: e.target.value })} />
                            <button type="button" onClick={() => setShowHooksToken(!showHooksToken)} className="absolute right-2 top-1/2 -translate-y-1/2 text-text-tertiary hover:text-text-primary transition-colors">
                                {showHooksToken ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                            </button>
                        </div>
                    </div>
                </div>
            </section>

            {/* Personality */}
            <section className="card space-y-4">
                <h3 className="text-sm font-semibold text-text-primary">Personality & Prompts</h3>
                <div>
                    <label className="block text-xs text-text-tertiary mb-1">System Prompt</label>
                    <textarea
                        className="input min-h-[120px] font-mono text-sm"
                        value={form.system_prompt}
                        onChange={(e) => setForm({ ...form, system_prompt: e.target.value })}
                        placeholder="You are a software engineering agent..."
                    />
                </div>
                <div>
                    <label className="block text-xs text-text-tertiary mb-1">Personality / Behavior Notes</label>
                    <textarea
                        className="input min-h-[80px] text-sm"
                        value={form.personality}
                        onChange={(e) => setForm({ ...form, personality: e.target.value })}
                        placeholder="Concise, prefers to ship fast, writes tests..."
                    />
                </div>
            </section>

            {/* Schedule */}
            <section className="card space-y-4">
                <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-text-primary">Work Schedule</h3>
                    <button
                        onClick={() => setSchedule({ ...schedule, enabled: !schedule.enabled })}
                        className={`flex items-center gap-1.5 text-sm font-medium px-3 py-1 rounded-full transition-colors ${
                            schedule.enabled ? 'bg-emerald-500/15 text-emerald-400' : 'bg-bg-hover text-text-tertiary'
                        }`}
                    >
                        {schedule.enabled ? <ToggleRight className="w-4 h-4" /> : <ToggleLeft className="w-4 h-4" />}
                        {schedule.enabled ? 'Enabled' : 'Disabled'}
                    </button>
                </div>
                <div className="grid grid-cols-3 gap-4">
                    <div>
                        <label className="block text-xs text-text-tertiary mb-1">Start Time</label>
                        <input type="time" className="input" value={schedule.start} onChange={(e) => setSchedule({ ...schedule, start: e.target.value })} />
                    </div>
                    <div>
                        <label className="block text-xs text-text-tertiary mb-1">End Time</label>
                        <input type="time" className="input" value={schedule.end} onChange={(e) => setSchedule({ ...schedule, end: e.target.value })} />
                    </div>
                    <div>
                        <label className="block text-xs text-text-tertiary mb-1">Timezone</label>
                        <input className="input" value={schedule.tz} onChange={(e) => setSchedule({ ...schedule, tz: e.target.value })} />
                    </div>
                </div>
                <div>
                    <label className="block text-xs text-text-tertiary mb-2">Work Days</label>
                    <div className="flex gap-2">
                        {DAY_OPTIONS.map((day) => (
                            <button
                                key={day}
                                onClick={() => toggleDay(day)}
                                className={`px-3 py-1.5 rounded-lg text-xs font-medium uppercase transition-colors ${
                                    activeDays.includes(day)
                                        ? 'bg-accent-primary text-white'
                                        : 'bg-bg-hover text-text-tertiary hover:text-text-secondary'
                                }`}
                            >
                                {day}
                            </button>
                        ))}
                    </div>
                </div>
            </section>

            {/* Save */}
            <div className="flex items-center gap-3">
                <button onClick={saveAgent} disabled={saving} className="btn btn-primary">
                    {saving ? 'Saving...' : 'Save Configuration'}
                </button>
                {msg && <span className={`text-sm ${msg.startsWith('Error') ? 'text-red-400' : 'text-emerald-400'}`}>{msg}</span>}
            </div>
        </div>
    );
}


// ── Webhooks Tab ───────────────────────────────────────────────────────

function WebhooksTab({ agentId }) {
    const [logs, setLogs] = useState([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const load = async () => {
            try {
                const data = await api.forge.listWebhookLogs(agentId);
                setLogs(data);
            } catch (err) {
                console.error(err);
            } finally {
                setLoading(false);
            }
        };
        load();
        const interval = setInterval(load, 10000);
        return () => clearInterval(interval);
    }, [agentId]);

    if (loading) return <div className="flex-1 flex items-center justify-center text-text-tertiary p-6">Loading webhook logs...</div>;

    return (
        <div className="p-6">
            {logs.length === 0 ? (
                <div className="text-center py-16 text-text-tertiary">
                    <Webhook className="w-10 h-10 mx-auto mb-3 opacity-40" />
                    <p>No webhook deliveries recorded yet.</p>
                    <p className="text-xs mt-2">Webhook events will appear here as they are sent and received.</p>
                </div>
            ) : (
                <div className="space-y-2">
                    {logs.map((log) => (
                        <div key={log.id} className={`card border-l-4 ${log.success ? 'border-l-emerald-500' : 'border-l-red-500'}`}>
                            <div className="flex items-center gap-3 mb-2">
                                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${
                                    log.direction === 'inbound' ? 'bg-blue-500/15 text-blue-400' : 'bg-purple-500/15 text-purple-400'
                                }`}>
                                    {log.direction === 'inbound' ? '← IN' : '→ OUT'}
                                </span>
                                <span className="text-sm text-text-primary font-medium">{log.event || 'unknown'}</span>
                                {log.status_code && (
                                    <span className={`text-xs px-1.5 py-0.5 rounded ${
                                        log.status_code < 400 ? 'bg-emerald-500/15 text-emerald-400' : 'bg-red-500/15 text-red-400'
                                    }`}>
                                        {log.status_code}
                                    </span>
                                )}
                                {log.duration_ms != null && (
                                    <span className="text-xs text-text-tertiary">{log.duration_ms}ms</span>
                                )}
                                <span className="text-xs text-text-tertiary ml-auto">{formatTime(log.created_at)}</span>
                            </div>
                            <div className="text-xs text-text-tertiary truncate">{log.url}</div>
                            {log.payload && (
                                <details className="mt-2 text-xs">
                                    <summary className="text-text-tertiary cursor-pointer hover:text-text-secondary">Payload</summary>
                                    <pre className="mt-1 p-2 bg-bg-hover rounded text-text-secondary overflow-auto max-h-32">{log.payload}</pre>
                                </details>
                            )}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}


// ── Live Tab ───────────────────────────────────────────────────────────

function LiveTab({ agentId, agent }) {
    const [messages, setMessages] = useState([]);
    const [runs, setRuns] = useState([]);
    const [paused, setPaused] = useState(false);
    const bottomRef = useRef(null);

    useEffect(() => {
        if (paused) return;
        const load = async () => {
            try {
                const [msgs, rs] = await Promise.all([
                    api.forge.listMessages(agentId, { limit: 30 }),
                    api.forge.listRuns({ agent_id: agentId, limit: 5 }),
                ]);
                setMessages(msgs);
                setRuns(rs);
            } catch (err) {
                console.error(err);
            }
        };
        load();
        const interval = setInterval(load, 2000);
        return () => clearInterval(interval);
    }, [agentId, paused]);

    useEffect(() => {
        if (!paused && bottomRef.current) {
            bottomRef.current.scrollIntoView({ behavior: 'smooth' });
        }
    }, [messages, paused]);

    const status = STATUS_STYLES[agent.status] || STATUS_STYLES.offline;

    return (
        <div className="flex flex-col h-full">
            {/* Live header */}
            <div className="flex items-center justify-between px-6 py-3 border-b border-border-subtle bg-bg-panel">
                <div className="flex items-center gap-3">
                    <div className={`w-2.5 h-2.5 rounded-full ${paused ? 'bg-gray-500' : 'bg-red-500 animate-pulse'}`} />
                    <span className="text-sm font-medium text-text-primary">{paused ? 'Paused' : 'Live Feed'}</span>
                    <span className="text-xs text-text-tertiary">Polling every 2s</span>
                </div>
                <div className="flex items-center gap-2">
                    {runs.length > 0 && runs[0].status === 'running' && (
                        <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full bg-yellow-500/15 text-yellow-400 text-xs font-medium animate-pulse">
                            <Loader className="w-3 h-3" /> Running: {runs[0].task_title || runs[0].trigger_event || 'task'}
                        </span>
                    )}
                    <button onClick={() => setPaused(!paused)} className="btn btn-ghost py-1 px-3 text-xs">
                        {paused ? <Play className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
                        {paused ? 'Resume' : 'Pause'}
                    </button>
                </div>
            </div>

            {/* Live feed */}
            <div className="flex-1 overflow-auto p-4 space-y-2 font-mono text-xs">
                {messages.length === 0 ? (
                    <div className="text-center py-16 text-text-tertiary">
                        <Eye className="w-10 h-10 mx-auto mb-3 opacity-40" />
                        <p>Waiting for agent activity...</p>
                    </div>
                ) : (
                    messages.map((msg) => {
                        const roleColors = {
                            system: '#a855f7', user: '#3b82f6', assistant: '#10b981', tool: '#f97316'
                        };
                        const color = roleColors[msg.role] || '#6b7280';
                        return (
                            <div key={msg.id} className="flex gap-2 leading-relaxed">
                                <span className="text-text-tertiary shrink-0 w-[70px] text-right">{formatTimeShort(msg.created_at)}</span>
                                <span className="shrink-0 font-bold w-[60px]" style={{ color }}>[{msg.role}]</span>
                                <span className="text-text-secondary flex-1 break-all">
                                    {msg.content.length > 300 ? msg.content.slice(0, 300) + '...' : msg.content}
                                    {msg.tool_name && <span className="text-orange-400 ml-1">→ {msg.tool_name}</span>}
                                </span>
                            </div>
                        );
                    })
                )}
                <div ref={bottomRef} />
            </div>
        </div>
    );
}


// ── Helpers ─────────────────────────────────────────────────────────────

function StatCard({ icon: Icon, label, value, sub, color }) {
    return (
        <div className="card flex items-start gap-4">
            <div className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0" style={{ backgroundColor: color + '18' }}>
                <Icon className="w-5 h-5" style={{ color }} />
            </div>
            <div>
                <div className="text-2xl font-bold text-text-primary">{value}</div>
                <div className="text-sm text-text-secondary">{label}</div>
                {sub && <div className="text-xs text-text-tertiary mt-1">{sub}</div>}
            </div>
        </div>
    );
}

function formatDuration(ms) {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
}

function timeAgo(isoString) {
    const diff = Date.now() - new Date(isoString).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
}

function formatTime(isoString) {
    return new Date(isoString).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function formatTimeShort(isoString) {
    return new Date(isoString).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
