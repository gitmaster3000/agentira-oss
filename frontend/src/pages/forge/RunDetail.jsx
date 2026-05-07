import React, { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
    ArrowLeft, Bot, Zap, Clock, DollarSign, AlertTriangle, CheckCircle,
    XCircle, Pause, Ban, RefreshCw, User, Wrench, MessageSquare,
} from 'lucide-react';
import { api } from '../../api';

const STATUS_CONFIG = {
    queued:        { bg: '#5f6368', label: 'Queued',   icon: Clock },
    pending:       { bg: '#5f6368', label: 'Pending',  icon: Clock },
    running:       { bg: '#f1c40f', label: 'Running',  icon: RefreshCw },
    waiting_human: { bg: '#ff9800', label: 'Waiting',  icon: Pause },
    blocked:       { bg: '#e91e63', label: 'Blocked',  icon: Ban },
    completed:     { bg: '#2ecc71', label: 'Completed', icon: CheckCircle },
    failed:        { bg: '#e74c3c', label: 'Failed',   icon: XCircle },
    cancelled:     { bg: '#9aa0a6', label: 'Cancelled', icon: Ban },
};

export function RunDetail() {
    const { runId } = useParams();
    const [run, setRun] = useState(null);
    const [events, setEvents] = useState([]);
    const [triggerEvent, setTriggerEvent] = useState(null);
    const [loading, setLoading] = useState(true);

    const load = async () => {
        try {
            const [r, evts] = await Promise.all([
                api.forge.getRun(runId),
                api.forge.listRunEvents(runId),
            ]);
            setRun(r);
            setEvents(evts);
            api.forge.getTriggerEvent(runId).then(setTriggerEvent).catch(() => {});
        } catch (err) {
            console.error('Failed to load run:', err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        load();
        const interval = setInterval(load, 5000);
        return () => clearInterval(interval);
    }, [runId]);

    if (loading) {
        return <div className="flex-1 flex items-center justify-center text-text-tertiary">Loading run...</div>;
    }

    if (!run) {
        return <div className="flex-1 flex items-center justify-center text-text-tertiary">Run not found</div>;
    }

    const s = STATUS_CONFIG[run.status] || STATUS_CONFIG.queued;
    const StatusIcon = s.icon;
    const totalTokens = (run.input_tokens || 0) + (run.output_tokens || 0) + (run.total_tokens || 0);
    const isActive = ['queued', 'pending', 'running', 'waiting_human', 'blocked'].includes(run.status);

    return (
        <div className="flex-1 p-6 space-y-6 max-w-5xl">
            {/* Back + Header */}
            <div className="flex items-center gap-3">
                <Link to="/forge/runs" className="text-text-tertiary hover:text-text-primary transition-colors">
                    <ArrowLeft className="w-5 h-5" />
                </Link>
                <div className="flex-1">
                    <div className="flex items-center gap-3">
                        <h1 className="text-2xl font-bold text-text-primary">Run {run.id}</h1>
                        <span
                            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-semibold text-white"
                            style={{ backgroundColor: s.bg }}
                        >
                            <StatusIcon className="w-3.5 h-3.5" />
                            {s.label}
                        </span>
                        {isActive && (
                            <span className="relative flex h-2.5 w-2.5">
                                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-yellow-400 opacity-75" />
                                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-yellow-500" />
                            </span>
                        )}
                    </div>
                    <p className="text-sm text-text-secondary mt-1">
                        {run.agent_name && <>Agent: <Link to={`/forge/agents/${run.agent_id}`} className="text-accent-primary hover:underline">{run.agent_name}</Link></>}
                        {run.task_title && <> &middot; Task: {run.task_title}</>}
                        {run.project_name && <> &middot; Project: {run.project_name}</>}
                    </p>
                </div>
                <button onClick={load} className="btn btn-ghost" title="Refresh">
                    <RefreshCw className="w-4 h-4" />
                </button>
            </div>

            {/* Summary */}
            {run.summary && (
                <div className="card bg-bg-hover border-l-4" style={{ borderLeftColor: s.bg }}>
                    <p className="text-sm text-text-primary">{run.summary}</p>
                </div>
            )}

            {/* Error */}
            {run.error && (
                <div className="card bg-red-500/5 border border-red-500/20">
                    <div className="flex items-start gap-3">
                        <AlertTriangle className="w-5 h-5 text-red-400 mt-0.5 flex-shrink-0" />
                        <div>
                            <div className="text-sm font-medium text-red-400 mb-1">Error</div>
                            <pre className="text-xs text-text-secondary whitespace-pre-wrap font-mono">{run.error}</pre>
                        </div>
                    </div>
                </div>
            )}

            {/* Metrics Grid */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                <MetricCard
                    icon={Clock} label="Duration"
                    value={run.duration_ms != null ? formatDuration(run.duration_ms) : '\u2014'}
                    color="#7c4dff"
                />
                <MetricCard
                    icon={Zap} label="Tokens"
                    value={totalTokens > 0 ? totalTokens.toLocaleString() : '\u2014'}
                    sub={totalTokens > 0 ? `${(run.input_tokens || 0).toLocaleString()} in / ${(run.output_tokens || 0).toLocaleString()} out` : null}
                    color="#00bcd4"
                />
                <MetricCard
                    icon={DollarSign} label="Cost"
                    value={run.cost_usd > 0 ? `$${run.cost_usd.toFixed(4)}` : '\u2014'}
                    color="#f1c40f"
                />
                <MetricCard
                    icon={Bot} label="Model"
                    value={run.model_used || '\u2014'}
                    sub={run.provider || null}
                    color="#2ecc71"
                />
            </div>

            {/* Timeline */}
            <div className="card">
                <h2 className="text-lg font-semibold text-text-primary mb-4">Timeline</h2>
                <div className="space-y-3">
                    <TimelineEntry label="Created" time={run.created_at} />
                    {run.started_at && <TimelineEntry label="Started" time={run.started_at} />}
                    {run.completed_at && <TimelineEntry label="Completed" time={run.completed_at} color="#2ecc71" />}
                    {run.cancelled_at && <TimelineEntry label="Cancelled" time={run.cancelled_at} color="#9aa0a6" />}
                    {run.finished_at && run.status === 'failed' && <TimelineEntry label="Failed" time={run.finished_at} color="#e74c3c" />}
                </div>
            </div>

            {/* Trigger Event */}
            {triggerEvent && (
                <div className="card">
                    <h2 className="text-lg font-semibold text-text-primary mb-4">Trigger Event</h2>
                    <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
                        <div><span className="text-text-tertiary">Source:</span> <span className="text-text-primary">{triggerEvent.source}</span></div>
                        <div><span className="text-text-tertiary">Type:</span> <span className="text-text-primary">{triggerEvent.event_type}</span></div>
                        <div><span className="text-text-tertiary">Actor:</span> <span className="text-text-primary">{triggerEvent.actor || '\u2014'}</span></div>
                        <div><span className="text-text-tertiary">Subject:</span> <span className="text-text-primary">{triggerEvent.subject_type ? `${triggerEvent.subject_type}:${triggerEvent.subject_id}` : '\u2014'}</span></div>
                    </div>
                </div>
            )}

            {/* Conversation — messages tagged with this run_id (one row per
                user prompt + every assistant text/tool event the daemon
                streamed back). Polls every 5s along with run state. */}
            <div className="card">
                <h2 className="text-lg font-semibold text-text-primary mb-4 flex items-center gap-2">
                    <MessageSquare className="w-5 h-5" /> Conversation
                </h2>
                {events.length === 0 ? (
                    <p className="text-sm text-text-tertiary">
                        {isActive ? 'Waiting for the agent…' : 'No messages on this run.'}
                    </p>
                ) : (
                    <div className="space-y-3">
                        {events.map((m) => (
                            <MessageRow key={m.id} m={m} />
                        ))}
                    </div>
                )}
            </div>

            {/* Trace ids — each turn shares one. Useful for grepping logs. */}
            {(() => {
                const traceIds = [...new Set(events.map(m => m.trace_id).filter(Boolean))];
                if (traceIds.length === 0) return null;
                return (
                    <div className="text-xs text-text-tertiary">
                        trace_id{traceIds.length > 1 ? 's' : ''}:{' '}
                        {traceIds.map(t => <code key={t} className="font-mono mr-2">{t}</code>)}
                    </div>
                );
            })()}

            {/* Metadata */}
            <div className="card">
                <h2 className="text-lg font-semibold text-text-primary mb-4">Details</h2>
                <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
                    <div><span className="text-text-tertiary">Run ID:</span> <span className="text-text-primary font-mono">{run.id}</span></div>
                    <div><span className="text-text-tertiary">Agent ID:</span> <span className="text-text-primary font-mono">{run.agent_id}</span></div>
                    {run.task_id && <div><span className="text-text-tertiary">Task ID:</span> <span className="text-text-primary font-mono">{run.task_id}</span></div>}
                    {run.project_id && <div><span className="text-text-tertiary">Project ID:</span> <span className="text-text-primary font-mono">{run.project_id}</span></div>}
                    {run.workspace_id && <div><span className="text-text-tertiary">Workspace:</span> <span className="text-text-primary font-mono">{run.workspace_id}</span></div>}
                    {run.trigger_event && <div><span className="text-text-tertiary">Trigger:</span> <span className="text-text-primary">{run.trigger_event}</span></div>}
                    {run.updated_at && <div><span className="text-text-tertiary">Last updated:</span> <span className="text-text-primary">{new Date(run.updated_at).toLocaleString()}</span></div>}
                </div>
            </div>
        </div>
    );
}

function MessageRow({ m }) {
    const role = m.role || 'assistant';
    const cfg = ROLE_CONFIG[role] || ROLE_CONFIG.assistant;
    const Icon = cfg.icon;
    return (
        <div className="flex gap-3">
            <div
                className="w-8 h-8 rounded-md flex items-center justify-center flex-shrink-0"
                style={{ backgroundColor: cfg.color + '18' }}
            >
                <Icon className="w-4 h-4" style={{ color: cfg.color }} />
            </div>
            <div className="flex-1 min-w-0">
                <div className="flex items-baseline gap-2 mb-1">
                    <span className="text-xs font-semibold text-text-primary capitalize">{cfg.label}</span>
                    {m.tool_name && role === 'tool' && (
                        <span className="text-xs text-text-tertiary font-mono">{m.tool_name}</span>
                    )}
                    {m.created_at && (
                        <span className="text-xs text-text-tertiary ml-auto">{timeAgo(m.created_at)}</span>
                    )}
                </div>
                <pre
                    className="text-sm text-text-secondary whitespace-pre-wrap break-words font-sans bg-bg-app/40 rounded-md p-3 border border-border-subtle/30"
                    style={{ wordBreak: 'break-word' }}
                >
                    {m.content || '(empty)'}
                </pre>
                {m.tool_input && (
                    <details className="mt-1 text-xs">
                        <summary className="cursor-pointer text-text-tertiary">tool input</summary>
                        <pre className="mt-1 p-2 bg-bg-app/40 rounded font-mono text-text-secondary overflow-x-auto">{m.tool_input}</pre>
                    </details>
                )}
            </div>
        </div>
    );
}

const ROLE_CONFIG = {
    user:      { icon: User,          label: 'You',       color: '#3b82f6' },
    assistant: { icon: Bot,           label: 'Agent',     color: '#10b981' },
    tool:      { icon: Wrench,        label: 'Tool',      color: '#f97316' },
    system:    { icon: MessageSquare, label: 'System',    color: '#a855f7' },
};

function MetricCard({ icon: Icon, label, value, sub, color }) {
    return (
        <div className="card flex items-start gap-3">
            <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0" style={{ backgroundColor: color + '18' }}>
                <Icon className="w-4 h-4" style={{ color }} />
            </div>
            <div className="min-w-0">
                <div className="text-lg font-bold text-text-primary truncate">{value}</div>
                <div className="text-xs text-text-secondary">{label}</div>
                {sub && <div className="text-xs text-text-tertiary mt-0.5 truncate">{sub}</div>}
            </div>
        </div>
    );
}

function TimelineEntry({ label, time, color = '#7c4dff' }) {
    return (
        <div className="flex items-center gap-3">
            <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: color }} />
            <span className="text-sm text-text-primary font-medium w-24">{label}</span>
            <span className="text-sm text-text-secondary">{new Date(time).toLocaleString()}</span>
            <span className="text-xs text-text-tertiary ml-auto">{timeAgo(time)}</span>
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
