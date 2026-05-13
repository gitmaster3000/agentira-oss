import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import {
    Bot, ArrowLeft, Wifi, WifiOff, Loader, Play, Clock, DollarSign,
    MessageSquare, Settings2, Activity, Webhook, Calendar, Send,
    ChevronDown, Eye, EyeOff, Zap, RefreshCw, ToggleLeft, ToggleRight,
    Terminal, User, Wrench, AlertCircle, CheckCircle, XCircle, Plus, X, Folder,
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
    { id: 'projects', label: 'Projects', icon: Folder },
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
                        <div className="text-sm text-text-tertiary flex items-center gap-2">
                            {agent.runtime_provider && (
                                <span
                                    className="px-1.5 py-0.5 rounded bg-emerald-500/15 text-xs text-emerald-400"
                                    title={agent.runtime_version || agent.runtime_provider}
                                >
                                    {agent.runtime_provider}
                                </span>
                            )}
                            <span>{agent.model || 'no model set'}</span>
                        </div>
                    </div>
                    <div className="flex items-center gap-4 text-sm text-text-secondary">
                        <span className="flex items-center gap-1"><Play className="w-3.5 h-3.5" /> {agent.total_runs} runs</span>
                        <span className="flex items-center gap-1"><DollarSign className="w-3.5 h-3.5" /> ${agent.total_cost_usd.toFixed(4)}</span>
                        {agent.status === 'busy' && (
                            <button
                                onClick={async () => {
                                    try {
                                        await api.forge.resetAgentStatus(agentId);
                                        loadAgent();
                                    } catch (err) {
                                        console.error('Reset failed:', err);
                                    }
                                }}
                                className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
                                title="Reset status — unstick agent and fail orphaned runs"
                            >
                                <RefreshCw className="w-3 h-3" /> Reset
                            </button>
                        )}
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
                {tab === 'overview' && <OverviewTab agent={agent} onTab={setTab} />}
                {tab === 'chat' && <ChatTab agentId={agentId} agent={agent} />}
                {tab === 'runs' && <RunsTab agentId={agentId} />}
                {tab === 'projects' && <ProjectsTab agentId={agentId} />}
                {tab === 'config' && <ConfigTab agent={agent} onSaved={loadAgent} />}
                {tab === 'webhooks' && <WebhooksTab agentId={agentId} />}
                {tab === 'live' && <LiveTab agentId={agentId} agent={agent} />}
            </div>
        </div>
    );
}


// ── Overview Tab ────────────────────────────────────────────────────────

function OverviewTab({ agent, onTab }) {
    const [costs, setCosts] = useState(null);
    const [runtimeCosts, setRuntimeCosts] = useState(null);
    const [runtimeStatus, setRuntimeStatus] = useState(null);
    const [pricing, setPricing] = useState(null);
    const [projects, setProjects] = useState([]);
    const [costFocus, setCostFocus] = useState(false);
    const costRef = useRef(null);

    useEffect(() => {
        api.forge.getAgentCosts(agent.id).then(setCosts).catch(console.error);
        api.forge.getRuntimeStatus(agent.id).then(setRuntimeStatus).catch(console.error);
        api.forge.getRuntimeCosts(agent.id).then(setRuntimeCosts).catch(console.error);
        api.forge.getPricing().then(setPricing).catch(console.error);
        api.forge.listAgentProjects(agent.id).then(setProjects).catch(() => setProjects([]));
    }, [agent.id]);

    const _price = (model) => {
        if (!model || !pricing) return null;
        return pricing[model] || pricing[`google/${model}`] || pricing[model.replace('google/', '')];
    };

    return (
        <div className="p-6 space-y-6">
            {/* Quick Stats */}
            {!costFocus && (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
                    <StatCard icon={Play} label="Total Runs" value={agent.total_runs} color="#7c4dff" />
                    <StatCard
                        icon={DollarSign}
                        label="Total Cost"
                        value={`$${(runtimeCosts?.runtime?.estimated_cost_usd || agent.total_cost_usd).toFixed(4)}`}
                        color="#f1c40f"
                        onClick={() => { setCostFocus(true); setTimeout(() => costRef.current?.scrollIntoView({ behavior: 'smooth' }), 50); }}
                        expandable
                    />
                    <StatCard
                        icon={Folder}
                        label="Assigned Projects"
                        value={projects.length}
                        sub={projects.length > 0
                            ? projects.slice(0, 2).map(p => p.name).join(', ') + (projects.length > 2 ? ` +${projects.length - 2} more` : '')
                            : 'Not in any project'}
                        color="#ec4899"
                        onClick={() => onTab && onTab('projects')}
                        expandable={projects.length > 0}
                    />
                    <StatCard icon={Clock} label="Last Heartbeat" value={agent.last_heartbeat ? timeAgo(agent.last_heartbeat) : 'Never'} color="#00bcd4" />
                    <StatCard
                        icon={Calendar}
                        label="Schedule"
                        value={agent.schedule_enabled ? `${agent.schedule_start} - ${agent.schedule_end}` : 'Disabled'}
                        sub={agent.schedule_enabled ? `${agent.schedule_tz} · ${agent.schedule_days}` : null}
                        color="#2ecc71"
                    />
                </div>
            )}

            {/* Cost Focus Header */}
            {costFocus && (
                <div className="flex items-center justify-between" ref={costRef}>
                    <h2 className="text-lg font-bold text-text-primary flex items-center gap-2">
                        <DollarSign className="w-5 h-5 text-yellow-400" />
                        Cost &amp; Usage Detail
                    </h2>
                    <button onClick={() => setCostFocus(false)} className="text-sm text-accent-primary hover:underline">Back to Overview</button>
                </div>
            )}

            {/* Cost Detail Table — shown in focus mode */}
            {costFocus && (
                <div className="card space-y-4">
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="text-xs text-text-tertiary uppercase tracking-wider border-b border-border-subtle">
                                    <th className="text-left pb-2 pr-4">Source / Model</th>
                                    <th className="text-right pb-2 px-3">Input Tokens</th>
                                    <th className="text-right pb-2 px-3">Output Tokens</th>
                                    <th className="text-right pb-2 px-3">Cache Read</th>
                                    <th className="text-right pb-2 px-3">Input $/1M</th>
                                    <th className="text-right pb-2 px-3">Output $/1M</th>
                                    <th className="text-right pb-2 px-3">Input Cost</th>
                                    <th className="text-right pb-2 px-3">Output Cost</th>
                                    <th className="text-right pb-2 pl-3">Total</th>
                                </tr>
                            </thead>
                            <tbody>
                                {/* Runtime rows */}
                                {runtimeCosts?.runtime && runtimeCosts.runtime.total_tokens > 0 && (() => {
                                    const rt = runtimeCosts.runtime;
                                    const p = _price(rt.model);
                                    const inC = rt.total_input_tokens / 1_000_000 * (p?.input || 0);
                                    const outC = rt.total_output_tokens / 1_000_000 * (p?.output || 0);
                                    return (
                                        <tr className="border-b border-border-subtle/50 bg-bg-hover/30">
                                            <td className="py-3 pr-4">
                                                <div className="text-text-primary font-medium">{rt.model}</div>
                                                <div className="text-xs text-text-tertiary">Runtime (OpenClaw) · {rt.session_count} sessions</div>
                                            </td>
                                            <td className="text-right py-3 px-3 text-text-secondary font-mono">{rt.total_input_tokens.toLocaleString()}</td>
                                            <td className="text-right py-3 px-3 text-text-secondary font-mono">{rt.total_output_tokens.toLocaleString()}</td>
                                            <td className="text-right py-3 px-3 text-text-tertiary font-mono">{(rt.total_cache_read || 0).toLocaleString()}</td>
                                            <td className="text-right py-3 px-3 text-text-tertiary">{p ? `$${p.input}` : '—'}</td>
                                            <td className="text-right py-3 px-3 text-text-tertiary">{p ? `$${p.output}` : '—'}</td>
                                            <td className="text-right py-3 px-3 text-text-secondary">${inC.toFixed(4)}</td>
                                            <td className="text-right py-3 px-3 text-text-secondary">${outC.toFixed(4)}</td>
                                            <td className="text-right py-3 pl-3 text-emerald-400 font-semibold">${(inC + outC).toFixed(4)}</td>
                                        </tr>
                                    );
                                })()}
                                {/* Forge tracked runs */}
                                {costs && Object.entries(costs.by_model).map(([model, data]) => {
                                    const p = _price(model);
                                    const inC = data.input_tokens / 1_000_000 * (p?.input || 0);
                                    const outC = data.output_tokens / 1_000_000 * (p?.output || 0);
                                    const total = data.cost_usd || (inC + outC);
                                    return (
                                        <tr key={model} className="border-b border-border-subtle/50">
                                            <td className="py-3 pr-4">
                                                <div className="text-text-primary font-medium">{model}</div>
                                                <div className="text-xs text-text-tertiary">Forge Runs · {data.runs} runs</div>
                                            </td>
                                            <td className="text-right py-3 px-3 text-text-secondary font-mono">{data.input_tokens.toLocaleString()}</td>
                                            <td className="text-right py-3 px-3 text-text-secondary font-mono">{data.output_tokens.toLocaleString()}</td>
                                            <td className="text-right py-3 px-3 text-text-tertiary">—</td>
                                            <td className="text-right py-3 px-3 text-text-tertiary">{p ? `$${p.input}` : '—'}</td>
                                            <td className="text-right py-3 px-3 text-text-tertiary">{p ? `$${p.output}` : '—'}</td>
                                            <td className="text-right py-3 px-3 text-text-secondary">${inC.toFixed(4)}</td>
                                            <td className="text-right py-3 px-3 text-text-secondary">${outC.toFixed(4)}</td>
                                            <td className="text-right py-3 pl-3 text-emerald-400 font-semibold">${total.toFixed(4)}</td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                    {/* Totals */}
                    {runtimeCosts?.runtime && (
                        <div className="flex justify-between items-center pt-3 border-t border-border-subtle text-sm">
                            <span className="text-text-tertiary">
                                Total: {(runtimeCosts.runtime.total_input_tokens + runtimeCosts.runtime.total_output_tokens).toLocaleString()} tokens
                            </span>
                            <span className="text-text-primary font-bold text-lg">
                                ${(runtimeCosts.runtime.estimated_cost_usd || 0).toFixed(4)}
                            </span>
                        </div>
                    )}
                </div>
            )}

            {/* OpenClaw Live Status — hidden in cost focus */}
            {!costFocus && (
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
                                            <span>{((s.input_tokens || 0) + (s.output_tokens || 0)).toLocaleString()} tok</span>
                                            {s.percent_used != null && (
                                                <span className={s.percent_used > 80 ? 'text-red-400 font-medium' : ''}>
                                                    {s.percent_used}% ctx
                                                </span>
                                            )}
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
            )}

            {/* Cost Breakdown — Runtime & Forge — hidden in cost focus */}
            {!costFocus && runtimeCosts?.runtime && runtimeCosts.runtime.total_tokens > 0 && (
                <div className="card">
                    <h3 className="text-sm font-semibold text-text-primary mb-3">Usage &amp; Cost (Runtime)</h3>
                    <div className="space-y-3">
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                            <div className="p-3 rounded-md bg-bg-hover">
                                <div className="text-xs text-text-tertiary mb-1">Input Tokens</div>
                                <div className="text-lg font-semibold text-text-primary">{runtimeCosts.runtime.total_input_tokens.toLocaleString()}</div>
                            </div>
                            <div className="p-3 rounded-md bg-bg-hover">
                                <div className="text-xs text-text-tertiary mb-1">Output Tokens</div>
                                <div className="text-lg font-semibold text-text-primary">{runtimeCosts.runtime.total_output_tokens.toLocaleString()}</div>
                            </div>
                            <div className="p-3 rounded-md bg-bg-hover">
                                <div className="text-xs text-text-tertiary mb-1">Cache Read</div>
                                <div className="text-lg font-semibold text-text-primary">{(runtimeCosts.runtime.total_cache_read || 0).toLocaleString()}</div>
                            </div>
                            <div className="p-3 rounded-md bg-bg-hover">
                                <div className="text-xs text-text-tertiary mb-1">Estimated Cost</div>
                                <div className="text-lg font-semibold text-emerald-400">${runtimeCosts.runtime.estimated_cost_usd.toFixed(4)}</div>
                            </div>
                        </div>
                        <div className="flex items-center gap-4 text-xs text-text-tertiary px-1">
                            <span>Model: <span className="text-text-secondary">{runtimeCosts.runtime.model}</span></span>
                            <span>Sessions: <span className="text-text-secondary">{runtimeCosts.runtime.session_count}</span></span>
                            {(() => {
                                const m = runtimeCosts.runtime.model;
                                if (!m || !pricing) return null;
                                const p = pricing[m] || pricing[`google/${m}`] || pricing[m.replace('google/', '')];
                                if (!p) return <span className="text-yellow-400">pricing not found for {m}</span>;
                                const inCost = (runtimeCosts.runtime.total_input_tokens / 1_000_000 * p.input);
                                const outCost = (runtimeCosts.runtime.total_output_tokens / 1_000_000 * p.output);
                                return <>
                                    <span>Input: <span className="text-text-secondary">${p.input}/1M tok</span></span>
                                    <span>Output: <span className="text-text-secondary">${p.output}/1M tok</span></span>
                                    <span>Calculated: <span className="text-emerald-400">${(inCost + outCost).toFixed(4)}</span></span>
                                </>;
                            })()}
                        </div>
                    </div>
                </div>
            )}

            {!costFocus && costs && Object.keys(costs.by_model).length > 0 && (
                <div className="card">
                    <h3 className="text-sm font-semibold text-text-primary mb-3">Cost Breakdown by Model (Forge Runs)</h3>
                    <div className="space-y-2">
                        {Object.entries(costs.by_model).map(([model, data]) => (
                            <div key={model} className="flex items-center justify-between px-3 py-2 rounded-md bg-bg-hover text-sm">
                                <div>
                                    <span className="text-text-primary font-medium">{model}</span>
                                    <span className="text-text-tertiary ml-2">{data.runs} runs</span>
                                </div>
                                <div className="flex items-center gap-4 text-text-secondary text-xs">
                                    <span>In: {data.input_tokens.toLocaleString()}</span>
                                    <span>Out: {data.output_tokens.toLocaleString()}</span>
                                    <span className="font-medium text-sm">${data.cost_usd.toFixed(4)}</span>
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

function ChatTab({ agentId, agent }) {
    const [messages, setMessages] = useState([]);
    const [loading, setLoading] = useState(true);
    const [autoScroll, setAutoScroll] = useState(true);
    const [input, setInput] = useState('');
    const [sending, setSending] = useState(false);
    // Project context for chat is no longer picked here. It resolves at
    // send time from the agent's assigned project + the current screen.
    // Users can inspect what's being sent via the `/context` slash command.
    // OR explicitly attach via the + button (popover lists the agent's
    // assigned projects); attached project overrides screen/default for
    // the next sends until removed.
    const [agentProjects, setAgentProjects] = useState([]);
    const [contextOpen, setContextOpen] = useState(false);
    const [attachedProject, setAttachedProject] = useState(null);
    const bottomRef = useRef(null);
    const containerRef = useRef(null);
    const inputRef = useRef(null);

    const msgCountRef = useRef(0);

    useEffect(() => {
        api.forge.listAgentProjects(agentId).then(setAgentProjects).catch(() => setAgentProjects([]));
    }, [agentId]);

    const loadMessages = useCallback(async () => {
        try {
            const data = await api.forge.listMessages(agentId, { limit: 200 });
            // Preserve any local-only messages (e.g. /context output) so the
            // 3s poll doesn't wipe them. They have id prefix "local-".
            setMessages((prev) => {
                const locals = (prev || []).filter(m => String(m.id).startsWith('local-'));
                return [...(data || []), ...locals];
            });
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

    // Resolve context client-side. Priority:
    //   1. explicit attached project (via + popover) — user override wins
    //   2. URL-derived project (when chatting from a project page)
    //   3. agent's default project (its Studio assignment)
    // Backend uses project_id to set the runtime cwd + load conventions + MCP.
    const buildUserContext = () => {
        const route = window.location.pathname;
        const studioProj = route.match(/\/studio\/board\/([^/]+)/);
        const forgeProj = route.match(/\/forge\/projects\/([^/]+)/);
        const screenProjectId = (studioProj || forgeProj)?.[1] || '';
        const project_id = attachedProject?.id || screenProjectId || agent?.default_project_id || '';
        const ctx = {
            surface: 'forge_agent_chat',
            route,
        };
        if (project_id) ctx.project_id = project_id;
        if (attachedProject?.name) ctx.project_name = attachedProject.name;
        return ctx;
    };

    const handleSend = async () => {
        if (!input.trim() || sending) return;
        const trimmed = input.trim();

        // `/context` slash command — show what would be sent, don't dispatch.
        if (trimmed === '/context' || trimmed.startsWith('/context ')) {
            const ctx = buildUserContext();
            let projectSource = 'none';
            if (ctx.project_id) {
                if (attachedProject?.id === ctx.project_id) projectSource = 'attached via +';
                else if (ctx.project_id === agent?.default_project_id) projectSource = 'agent assignment';
                else projectSource = 'current screen';
            }
            setInput('');
            inputRef.current?.focus();
            try {
                const preview = await api.forge.getDispatchPreview(agentId, ctx.project_id);
                setMessages((prev) => [
                    ...prev,
                    {
                        id: `local-context-${Date.now()}`,
                        role: 'system',
                        content: '',  // unused — preview field drives the render
                        preview: { ...preview, ctx, projectSource },
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

        setSending(true);
        try {
            await api.forge.sendRuntimeChat(agentId, {
                content: trimmed,
                user_context: buildUserContext(),
            });
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
                <span className="text-sm text-text-secondary">
                    {messages.length} messages
                    <span className="text-text-tertiary ml-2">· type <code>/context</code> to inspect what's being sent</span>
                </span>
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
                                {msg.preview
                                    ? <ContextPreviewCard preview={msg.preview} />
                                    : <pre className="text-sm text-text-primary whitespace-pre-wrap font-mono leading-relaxed">{msg.content}</pre>}
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
            <div className="px-6 py-3 border-t border-border-subtle bg-bg-panel">
                {/* Attached-context chip + project picker popover */}
                {(attachedProject || contextOpen) && (
                    <div className="mb-2 flex items-start gap-2 flex-wrap">
                        {attachedProject && (
                            <div className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-accent-subtle text-accent-primary text-xs">
                                <span>📎 {attachedProject.name}</span>
                                <button
                                    onClick={() => setAttachedProject(null)}
                                    className="hover:text-text-primary"
                                    title="Remove attachment"
                                >
                                    <X className="w-3 h-3" />
                                </button>
                            </div>
                        )}
                        {contextOpen && (
                            <div className="rounded-md border border-border-subtle bg-bg-panel p-2 w-full max-w-sm">
                                <div className="text-[10px] uppercase tracking-wider text-text-tertiary mb-1.5 px-1">
                                    Attach project context
                                </div>
                                {agentProjects.length === 0 ? (
                                    <div className="text-xs text-text-tertiary px-2 py-2">
                                        Agent isn't assigned to any project yet.
                                    </div>
                                ) : (
                                    agentProjects.map((p) => (
                                        <button
                                            key={p.id}
                                            onClick={() => { setAttachedProject(p); setContextOpen(false); }}
                                            className="w-full text-left px-2 py-1.5 rounded hover:bg-bg-hover text-sm text-text-primary flex items-center justify-between"
                                        >
                                            <span className="truncate">{p.name}</span>
                                            {p.key_prefix && (
                                                <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-bg-hover text-text-tertiary ml-2">{p.key_prefix}</span>
                                            )}
                                        </button>
                                    ))
                                )}
                            </div>
                        )}
                    </div>
                )}
                {/* Slash-command auto-suggest */}
                <SlashCommandSuggest input={input} onPick={(cmd) => {
                    setInput(cmd + ' ');
                    inputRef.current?.focus();
                }} />
                <div className="flex items-center gap-2">
                    <button
                        onClick={() => setContextOpen(!contextOpen)}
                        className="btn btn-ghost py-2.5 px-2.5"
                        title="Attach a project to this chat"
                    >
                        <Plus className="w-4 h-4" />
                    </button>
                    <input
                        ref={inputRef}
                        className="input flex-1"
                        placeholder="Send a message — / for commands"
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
        </div>
    );
}


// ── Slash-command suggestion popover ───────────────────────────────────

const SLASH_COMMANDS = [
    { name: '/context', desc: 'Show what context (project, MCP, env, prompts) will be sent on the next message' },
];

function SlashCommandSuggest({ input, onPick }) {
    if (!input.startsWith('/')) return null;
    const query = input.slice(1).split(/\s/)[0].toLowerCase();
    const matches = SLASH_COMMANDS.filter(c => c.name.slice(1).startsWith(query));
    if (matches.length === 0) return null;
    return (
        <div className="mb-2 rounded-md border border-border-subtle bg-bg-panel shadow-lg overflow-hidden">
            <div className="text-[10px] uppercase tracking-wider text-text-tertiary px-3 py-1.5 bg-bg-hover/50">
                Slash commands
            </div>
            {matches.map(cmd => (
                <button
                    key={cmd.name}
                    onClick={() => onPick(cmd.name)}
                    className="w-full text-left px-3 py-2 hover:bg-bg-hover flex items-center gap-3 transition-colors"
                >
                    <code className="text-sm text-accent-primary font-mono">{cmd.name}</code>
                    <span className="text-xs text-text-tertiary truncate">{cmd.desc}</span>
                </button>
            ))}
        </div>
    );
}


// ── Context preview card (renders the /context output as a structured panel) ───

function ContextPreviewCard({ preview }) {
    const p = preview || {};
    const proj = p.project || {};
    const ag = p.agent || {};
    const env = p.env_vars || {};
    const sp = p.system_prompt_addenda || {};
    const persona = p.persona_system_prompt || '';
    return (
        <div className="text-sm">
            <div className="text-xs text-text-tertiary mb-3 flex items-center gap-2">
                <span className="font-mono px-1.5 py-0.5 rounded bg-bg-hover">/context</span>
                <span>for @{ag.name || '—'}</span>
            </div>

            <Section label="Project">
                {proj.id ? (
                    <>
                        <Row k="name" v={proj.name || proj.id} />
                        {proj.source && <Row k="source" v={proj.source.replace('_', ' ')} />}
                        {proj.repo_path && <Row k="repo" v={<code className="text-xs">{proj.repo_path}</code>} />}
                        {proj.conventions_md_preview && (
                            <Row k="conventions" v={<em className="text-text-tertiary">"{proj.conventions_md_preview.slice(0, 140)}{proj.conventions_md_preview.length > 140 ? '…' : ''}"</em>} />
                        )}
                    </>
                ) : (
                    <div className="text-xs text-text-tertiary italic">— none. Chat runs without a project cwd.</div>
                )}
            </Section>

            <Section label="Runtime">
                <Row k="provider" v={<span className="px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400 text-xs">{ag.runtime_provider || '—'}</span>} />
                <Row k="model" v={ag.model || '—'} />
            </Section>

            <Section label="MCP servers">
                {p.mcp_servers?.length ? (
                    <div className="flex flex-wrap gap-1.5">
                        {p.mcp_servers.map(s => (
                            <span key={s} className="px-2 py-0.5 rounded bg-accent-subtle text-accent-primary text-xs font-mono">{s}</span>
                        ))}
                    </div>
                ) : (
                    <div className="text-xs text-text-tertiary italic">— none (no project bound)</div>
                )}
            </Section>

            <Section label="Env vars">
                <div className="text-xs text-text-tertiary mb-1">Injected by daemon:</div>
                <div className="flex flex-wrap gap-1.5 mb-2">
                    {(env.injected_by_daemon || []).map(k => (
                        <span key={k} className="px-2 py-0.5 rounded bg-bg-hover text-text-secondary text-xs font-mono">{k}</span>
                    ))}
                </div>
                {env.user_provided_names?.length > 0 ? (
                    <>
                        <div className="text-xs text-text-tertiary mb-1">User-provided secrets (names only):</div>
                        <div className="flex flex-wrap gap-1.5">
                            {env.user_provided_names.map(k => (
                                <span key={k} className="px-2 py-0.5 rounded bg-yellow-500/15 text-yellow-400 text-xs font-mono">{k}</span>
                            ))}
                        </div>
                    </>
                ) : (
                    <div className="text-xs text-text-tertiary italic">No user-provided secrets yet</div>
                )}
            </Section>

            <Section label="System-prompt addenda">
                <Row k="conventions pointer" v={<Yes v={sp.conventions_pointer_will_be_added} />} />
                <Row k="memory tool hint" v={<Yes v={sp.memory_addendum_will_be_added} />} />
                <Row k="screen/page preamble" v={<Yes v={true} />} />
            </Section>

            {persona && (
                <Section label="Persona system prompt">
                    <div className="text-xs text-text-secondary italic max-h-24 overflow-auto bg-bg-hover/50 rounded p-2 font-mono">
                        "{persona.slice(0, 400)}{persona.length > 400 ? '…' : ''}"
                    </div>
                </Section>
            )}

            <div className="text-[11px] text-text-tertiary mt-3 pt-2 border-t border-border-subtle/40">
                Task context (<code>mcp__agentira__get_task</code>) is pulled on demand by the agent — not eagerly attached.
            </div>
        </div>
    );
}

function Section({ label, children }) {
    return (
        <div className="mb-3">
            <div className="text-[10px] uppercase tracking-wider text-text-tertiary mb-1.5">{label}</div>
            {children}
        </div>
    );
}

function Row({ k, v }) {
    return (
        <div className="flex items-baseline gap-2 mb-0.5">
            <span className="text-text-tertiary text-xs w-28 shrink-0">{k}</span>
            <span className="text-sm text-text-primary flex-1 min-w-0 truncate">{v}</span>
        </div>
    );
}

function Yes({ v }) {
    return v
        ? <span className="text-emerald-400 text-xs">✓ yes</span>
        : <span className="text-text-tertiary text-xs">— no</span>;
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
        name: agent.name || '',
        model: agent.model || '',
        runtime_id: agent.runtime_id || '',
        default_project_id: agent.default_project_id || '',
        system_prompt: agent.system_prompt || '',
        personality: agent.personality || '',
    });
    const [runtimes, setRuntimes] = useState([]);
    const [projects, setProjects] = useState([]);
    const [saving, setSaving] = useState(false);
    const [msg, setMsg] = useState('');

    useEffect(() => {
        api.forge.listRuntimes().catch(() => []).then((rts) => setRuntimes(rts || []));
        api.getProjects().catch(() => []).then((ps) => setProjects(ps || []));
    }, []);

    const selectedRuntime = runtimes.find((r) => r.id === form.runtime_id) || null;
    // Models surfaced by the daemon for the selected runtime. Free-form input
    // still works via the datalist — type anything claude-code accepts.
    const runtimeModels = selectedRuntime?.models || [];

    const saveAgent = async () => {
        setSaving(true);
        try {
            await api.forge.updateAgent(agent.id, form);
            setMsg('Saved');
            onSaved();
            setTimeout(() => setMsg(''), 2000);
        } catch (err) {
            setMsg('Error: ' + err.message);
        } finally {
            setSaving(false);
        }
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
                        <input
                            className="input"
                            list="agent-model-options"
                            value={form.model}
                            onChange={(e) => setForm({ ...form, model: e.target.value })}
                            placeholder={runtimeModels[0] || 'sonnet'}
                        />
                        <datalist id="agent-model-options">
                            {runtimeModels.map((m) => <option key={m} value={m} />)}
                        </datalist>
                        <p className="text-xs text-text-tertiary mt-1">
                            Pick from the daemon's catalog or type any value (e.g. <code>sonnet</code>, <code>claude-sonnet-4-5</code>, <code>sonnet[1m]</code>).
                        </p>
                    </div>
                    {/* AP-86: no more "bot profile" picker. The agent IS the
                        profile (1:1 by id). Identity is implicit. */}
                    <div className="col-span-2">
                        <label className="block text-xs text-text-tertiary mb-1">Project assignment</label>
                        <select
                            className="input"
                            value={form.default_project_id}
                            onChange={(e) => setForm({ ...form, default_project_id: e.target.value })}
                        >
                            <option value="">— none (generic agent) —</option>
                            {projects.map(p => (
                                <option key={p.id} value={p.id}>
                                    {p.name}{p.repo_path ? ` · ${p.repo_path}` : ''}
                                </option>
                            ))}
                        </select>
                        <p className="text-xs text-text-tertiary mt-1">
                            Chats from this agent default to this project's repo + conventions + MCP — no need to pick per chat. Users can still override for a single chat session via the dropdown on the Chat tab.
                        </p>
                    </div>
                </div>
            </section>

            {/* Daemon Runtime */}
            <section className="card space-y-4">
                <h3 className="text-sm font-semibold text-text-primary">Daemon Runtime</h3>
                <p className="text-xs text-text-tertiary">
                    Which detected daemon runtime executes this agent. Runtimes are auto-registered when <code>agentira daemon start</code> runs.
                </p>
                <p className="text-xs text-text-tertiary">
                    The runtime is an <strong>execution engine</strong> for this agent. Persona, tools, conventions, and memory are owned by Agentira and travel with the agent across runtimes — change the runtime here and the same agent runs on a different engine.
                </p>
                {runtimes.length === 0 ? (
                    <div className="px-3 py-4 rounded-md bg-bg-hover text-sm text-text-tertiary">
                        No daemon runtimes registered. Start the daemon on a machine with claude-code / codex / gemini-cli installed.
                    </div>
                ) : (
                    <>
                        <div>
                            <label className="block text-xs text-text-tertiary mb-1">Runtime</label>
                            <select
                                className="input"
                                value={form.runtime_id}
                                onChange={(e) => setForm({ ...form, runtime_id: e.target.value, model: '' })}
                            >
                                <option value="">— select runtime —</option>
                                {runtimes.map((r) => (
                                    <option key={r.id} value={r.id}>
                                        {r.provider} {r.version ? `· ${r.version}` : ''} {r.device_name ? `· ${r.device_name}` : ''} ({r.status})
                                    </option>
                                ))}
                            </select>
                        </div>
                        {selectedRuntime && (
                            <div className="grid grid-cols-2 gap-3 text-xs">
                                <Info label="Provider" value={selectedRuntime.provider} />
                                <Info label="Version" value={selectedRuntime.version || '—'} />
                                <Info label="Device" value={selectedRuntime.device_name || '—'} />
                                <Info label="Status" value={selectedRuntime.status} accent={selectedRuntime.status === 'online' ? '#10b981' : '#9aa0a6'} />
                                <div className="col-span-2">
                                    <Info label="Binary" value={selectedRuntime.binary_path} mono />
                                </div>
                                {selectedRuntime.models?.length > 0 && (
                                    <div className="col-span-2">
                                        <Info label={`Models (${selectedRuntime.models.length})`} value={selectedRuntime.models.join(', ')} mono />
                                    </div>
                                )}
                            </div>
                        )}
                    </>
                )}
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

            {/* Schedule — placeholder */}
            <section className="card space-y-2 opacity-60">
                <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2">
                        <Calendar className="w-4 h-4" />
                        Work Schedule
                    </h3>
                    <span className="px-2 py-0.5 rounded-full text-xs bg-bg-hover text-text-tertiary">Coming soon</span>
                </div>
                <p className="text-xs text-text-tertiary">
                    Cron-style scheduling will be wired up via the daemon's scheduler. For now, agents only fire on explicit triggers.
                </p>
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

function Info({ label, value, mono, accent }) {
    return (
        <div>
            <div className="text-text-tertiary uppercase tracking-wider text-[10px] mb-0.5">{label}</div>
            <div
                className={`text-text-primary ${mono ? 'font-mono break-all' : ''}`}
                style={accent ? { color: accent } : undefined}
            >
                {value}
            </div>
        </div>
    );
}


// ── Projects Tab ───────────────────────────────────────────────────────

function ProjectsTab({ agentId }) {
    const navigate = useNavigate();
    const [projects, setProjects] = useState(null);

    useEffect(() => {
        api.forge.listAgentProjects(agentId)
            .then(d => setProjects(Array.isArray(d) ? d : []))
            .catch(() => setProjects([]));
    }, [agentId]);

    if (projects === null) {
        return <div className="flex-1 flex items-center justify-center text-text-tertiary p-6">Loading projects...</div>;
    }

    if (projects.length === 0) {
        return (
            <div className="p-6">
                <div className="text-center py-16 text-text-tertiary">
                    <Folder className="w-10 h-10 mx-auto mb-3 opacity-40" />
                    <p>This agent isn't assigned to any project yet.</p>
                    <p className="text-xs mt-2">Add the agent as a member from a project's settings to give it access.</p>
                </div>
            </div>
        );
    }

    return (
        <div className="p-6">
            <div className="card p-0 overflow-hidden">
                <table className="w-full text-sm">
                    <thead>
                        <tr className="border-b border-border-subtle text-text-tertiary text-xs uppercase">
                            <th className="text-left px-4 py-3 font-medium">Project</th>
                            <th className="text-left px-4 py-3 font-medium">Key</th>
                            <th className="text-left px-4 py-3 font-medium">Repo Path</th>
                        </tr>
                    </thead>
                    <tbody>
                        {projects.map(p => (
                            <tr
                                key={p.id}
                                onClick={() => navigate(`/studio/board/${p.id}`)}
                                className="border-b border-border-subtle hover:bg-bg-hover transition-colors cursor-pointer"
                            >
                                <td className="px-4 py-3 text-text-primary font-medium">{p.name}</td>
                                <td className="px-4 py-3 text-text-tertiary text-xs">
                                    {p.key_prefix
                                        ? <span className="px-1.5 py-0.5 rounded bg-bg-hover">{p.key_prefix}</span>
                                        : '—'}
                                </td>
                                <td className="px-4 py-3 text-text-tertiary text-xs font-mono truncate max-w-[400px]">
                                    {p.repo_path || '—'}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
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

function StatCard({ icon: Icon, label, value, sub, color, onClick, expandable }) {
    return (
        <div
            className={`card flex items-start gap-4 ${onClick ? 'cursor-pointer hover:border-border-active transition-colors' : ''}`}
            onClick={onClick}
        >
            <div className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0" style={{ backgroundColor: color + '18' }}>
                <Icon className="w-5 h-5" style={{ color }} />
            </div>
            <div className="flex-1">
                <div className="text-2xl font-bold text-text-primary">{value}</div>
                <div className="text-sm text-text-secondary">{label}</div>
                {sub && <div className="text-xs text-text-tertiary mt-1">{sub}</div>}
            </div>
            {expandable && <ChevronDown className="w-4 h-4 text-text-tertiary mt-1" />}
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
