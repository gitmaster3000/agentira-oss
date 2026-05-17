import React, { useState, useEffect } from 'react';
import { useParams, Link, useSearchParams, useNavigate } from 'react-router-dom';
import {
    ArrowLeft, Bot, Zap, Clock, DollarSign, AlertTriangle, CheckCircle,
    XCircle, Pause, Play, Ban, RefreshCw, User, Wrench, MessageSquare,
    ClipboardList, Folder,
} from 'lucide-react';
import { api } from '../../api';
import { Breadcrumbs } from '../../components/Breadcrumbs';

const STATUS_CONFIG = {
    queued:        { bg: '#5f6368', label: 'Queued',   icon: Clock },
    // AP-112: READY = prepared, waiting for the user to review/edit the
    // prompt and press Start. Visually distinct from PENDING so users see
    // "this is waiting on me", not "this is queued".
    ready:         { bg: '#3b82f6', label: 'Ready',    icon: Play },
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
    const [searchParams] = useSearchParams();
    // AP-109: entry-point hint. `?from=runs` means user clicked in from a
    // cross-agent list (global Runs page, Forge overview); breadcrumb falls
    // back to `Forge › Runs › Run X` instead of the agent path. Absence of
    // the param (e.g. agent-runs-tab click, shared link) uses agent path.
    const from = searchParams.get('from');
    const navigate = useNavigate();
    const [run, setRun] = useState(null);
    const [events, setEvents] = useState([]);
    const [triggerEvent, setTriggerEvent] = useState(null);
    const [loading, setLoading] = useState(true);
    // AP-112: prompt editor state for PENDING runs. Seeded from
    // run.initial_prompt on first load; user edits in-place.
    const [editedPrompt, setEditedPrompt] = useState(null);
    const [starting, setStarting] = useState(false);

    const load = async () => {
        try {
            const [r, evts] = await Promise.all([
                api.forge.getRun(runId),
                api.forge.listRunEvents(runId),
            ]);
            setRun(r);
            setEvents(evts);
            // AP-112: seed the editor once with the server-stored prompt.
            // Don't overwrite on subsequent polls (would clobber the user's
            // typing). The editor only matters while status === 'pending'.
            setEditedPrompt((prev) => prev == null ? (r.initial_prompt || '') : prev);
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
    // AP-112: READY = the prompt-editor screen. Hide the top
    // pause/resume/stop controls there — they're meaningless before
    // dispatch, and the editor card has its own Start/Discard buttons.
    const isReady = run.status === 'ready';

    return (
        <div className="flex-1 p-6 space-y-6 max-w-5xl">
            <Breadcrumbs entity="run" data={run} opts={{ from }} />
            {/* Header */}
            <div className="flex items-center gap-3">
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
                    {/* AP-109: meaningful quick-links instead of bare IDs.
                        Explicit "<Type>: <Name>" labels so a glance tells
                        you what each pill is. Chat opens the agent chat
                        pinned to this task's scope (Stop in chat = Pause). */}
                    <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
                        {run.agent_name && (
                            <Link
                                to={`/forge/agents/${run.agent_id}`}
                                className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-bg-hover hover:bg-bg-app text-xs text-text-secondary hover:text-text-primary"
                            >
                                <Bot className="w-3 h-3" />
                                <span className="text-text-tertiary">Agent:</span>
                                <span>{run.agent_name}</span>
                            </Link>
                        )}
                        {run.task_id && (
                            <Link
                                to={`/studio/tasks/${run.task_id}`}
                                className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-bg-hover hover:bg-bg-app text-xs text-text-secondary hover:text-text-primary"
                                title={run.task_title || run.task_id}
                            >
                                <ClipboardList className="w-3 h-3" />
                                <span className="text-text-tertiary">Task:</span>
                                <span>{run.task_key || run.task_title || run.task_id.slice(0, 8)}</span>
                            </Link>
                        )}
                        {run.project_id && (
                            <Link
                                to={`/studio/project/${run.project_id}`}
                                className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-bg-hover hover:bg-bg-app text-xs text-text-secondary hover:text-text-primary"
                            >
                                <Folder className="w-3 h-3" />
                                <span className="text-text-tertiary">Project:</span>
                                <span>{run.project_name || run.project_id.slice(0, 8)}</span>
                            </Link>
                        )}
                    </div>
                </div>
                {/* Run controls — pause / resume / stop. Pause is best-effort
                    for CLI runtimes (SIGSTOP); openclaw HTTP runs ignore
                    pause. Stop is terminal. */}
                {!isReady && run.status === 'running' && (
                    <button
                        onClick={async () => {
                            try {
                                await api.forge.pauseRun(runId);
                                await load();
                            } catch (err) {
                                alert('Pause failed: ' + (err.message || err));
                            }
                        }}
                        className="btn btn-ghost text-yellow-500 hover:bg-yellow-500/10"
                        title="Pause (best-effort — long pauses may hit API timeouts)"
                    >
                        <Pause className="w-4 h-4" /> Pause
                    </button>
                )}
                {!isReady && run.status === 'paused' && (
                    <button
                        onClick={async () => {
                            try {
                                await api.forge.resumeRun(runId);
                                await load();
                            } catch (err) {
                                alert('Resume failed: ' + (err.message || err));
                            }
                        }}
                        className="btn btn-ghost text-green-500 hover:bg-green-500/10"
                        title="Resume"
                    >
                        <Play className="w-4 h-4" /> Resume
                    </button>
                )}
                {!isReady && isActive && (
                    <button
                        onClick={async () => {
                            if (!window.confirm('Stop this run? The agent will be killed; this cannot be undone.')) return;
                            try {
                                await api.forge.cancelRun(runId);
                                await load();
                            } catch (err) {
                                alert('Stop failed: ' + (err.message || err));
                            }
                        }}
                        className="btn btn-ghost text-red-400 hover:text-red-500 hover:bg-red-500/10"
                        title="Stop this run (terminal — cannot be resumed)"
                    >
                        <Ban className="w-4 h-4" /> Stop
                    </button>
                )}
                {!isReady && (
                    <button onClick={load} className="btn btn-ghost" title="Refresh">
                        <RefreshCw className="w-4 h-4" />
                    </button>
                )}
            </div>

            {/* AP-112: editable prompt for PENDING runs.
                The user landed here from clicking Run on a task. The prompt
                was built server-side from task title/description/DoD and
                persisted on the Run row. Edit, Start to dispatch, Discard
                to throw away. Once dispatched, this card disappears (status
                flips to running and the rest of the page takes over). */}
            {isReady && (
                <div className="card border border-accent-primary/30">
                    <div className="flex items-center justify-between mb-3">
                        <h2 className="text-lg font-semibold text-text-primary flex items-center gap-2">
                            <Play className="w-5 h-5" /> Review prompt before starting
                        </h2>
                        <span className="text-xs text-text-tertiary">
                            Sent verbatim to the agent on Start
                        </span>
                    </div>
                    <textarea
                        value={editedPrompt || ''}
                        onChange={(e) => setEditedPrompt(e.target.value)}
                        className="w-full min-h-[280px] bg-bg-app border border-border-subtle rounded-md p-3 text-sm font-mono text-text-primary focus:outline-none focus:border-accent-primary resize-y"
                        placeholder="The prompt the agent will receive…"
                        disabled={starting}
                    />
                    <div className="flex items-center gap-2 mt-3">
                        <button
                            disabled={starting || !editedPrompt?.trim()}
                            onClick={async () => {
                                setStarting(true);
                                try {
                                    await api.forge.dispatchRun(runId, editedPrompt);
                                    await load();
                                } catch (err) {
                                    alert('Start failed: ' + (err.message || err));
                                } finally {
                                    setStarting(false);
                                }
                            }}
                            className="btn btn-primary"
                        >
                            <Play className="w-4 h-4" />
                            {starting ? 'Starting…' : 'Start run'}
                        </button>
                        <button
                            disabled={starting}
                            onClick={() => {
                                if (editedPrompt !== (run.initial_prompt || '')) {
                                    if (!window.confirm('Reset the prompt to the original?')) return;
                                }
                                setEditedPrompt(run.initial_prompt || '');
                            }}
                            className="btn btn-ghost"
                            title="Reset to the server-built prompt"
                        >
                            <RefreshCw className="w-4 h-4" /> Reset
                        </button>
                        <div className="flex-1" />
                        <button
                            disabled={starting}
                            onClick={async () => {
                                if (!window.confirm('Discard this run? The PENDING row will be deleted.')) return;
                                try {
                                    await api.forge.discardRun(runId);
                                    navigate(-1);
                                } catch (err) {
                                    alert('Discard failed: ' + (err.message || err));
                                }
                            }}
                            className="btn btn-ghost text-red-400 hover:text-red-500 hover:bg-red-500/10"
                            title="Delete this pending run"
                        >
                            <Ban className="w-4 h-4" /> Discard
                        </button>
                    </div>
                </div>
            )}

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
                streamed back). Polls every 5s along with run state.
                AP-109: when there's a task, the whole card is a link to
                the live agent chat scoped to this task, so the read-only
                thread here becomes send-able with one click. */}
            {(() => {
                const inner = (
                    <>
                        <h2 className="text-lg font-semibold text-text-primary mb-4 flex items-center gap-2">
                            <MessageSquare className="w-5 h-5" /> Conversation
                            {run.task_id && run.agent_id && (
                                <span className="ml-auto text-xs text-accent-primary opacity-0 group-hover:opacity-100 transition-opacity">
                                    Open in chat →
                                </span>
                            )}
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
                    </>
                );
                if (run.task_id && run.agent_id) {
                    return (
                        <Link
                            to={`/forge/agents/${run.agent_id}?tab=chat&scope=${encodeURIComponent(`task:${run.task_id}`)}`}
                            className="card block group hover:border-accent-primary/40 transition-colors"
                            title="Open in agent chat — Stop in chat pauses this run"
                        >
                            {inner}
                        </Link>
                    );
                }
                return <div className="card">{inner}</div>;
            })()}

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

            {/* Metadata — AP-109: meaningful links, not bare IDs. Each row
                shows the human label as the primary link and tucks the raw
                id underneath in small monospace for grep-ability. */}
            <div className="card">
                <h2 className="text-lg font-semibold text-text-primary mb-4">Details</h2>
                <div className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
                    <DetailLink
                        label="Agent"
                        to={`/forge/agents/${run.agent_id}`}
                        primary={run.agent_name || `agent ${run.agent_id.slice(0, 8)}`}
                        id={run.agent_id}
                        icon={Bot}
                    />
                    {run.task_id && (
                        <DetailLink
                            label="Task"
                            to={`/studio/tasks/${run.task_id}`}
                            primary={run.task_title || run.task_key || `task ${run.task_id.slice(0, 8)}`}
                            sub={run.task_key && run.task_title ? run.task_key : null}
                            id={run.task_id}
                            icon={ClipboardList}
                        />
                    )}
                    {run.project_id && (
                        <DetailLink
                            label="Project"
                            to={`/studio/project/${run.project_id}`}
                            primary={run.project_name || `project ${run.project_id.slice(0, 8)}`}
                            id={run.project_id}
                            icon={Folder}
                        />
                    )}
                    <div>
                        <div className="text-text-tertiary text-xs uppercase tracking-wider mb-0.5">Run</div>
                        <div className="text-text-primary font-mono text-xs">{run.id}</div>
                    </div>
                    {run.workspace_id && (
                        <div>
                            <div className="text-text-tertiary text-xs uppercase tracking-wider mb-0.5">Workspace</div>
                            <div className="text-text-primary font-mono text-xs">{run.workspace_id}</div>
                        </div>
                    )}
                    {run.trigger_event && (
                        <div>
                            <div className="text-text-tertiary text-xs uppercase tracking-wider mb-0.5">Trigger</div>
                            <div className="text-text-primary">{run.trigger_event}</div>
                        </div>
                    )}
                    {run.updated_at && (
                        <div>
                            <div className="text-text-tertiary text-xs uppercase tracking-wider mb-0.5">Last updated</div>
                            <div className="text-text-primary">{new Date(run.updated_at).toLocaleString()}</div>
                        </div>
                    )}
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

function DetailLink({ label, to, primary, sub, id, icon: Icon }) {
    return (
        <Link to={to} className="block group">
            <div className="text-text-tertiary text-xs uppercase tracking-wider mb-0.5">{label}</div>
            <div className="flex items-center gap-1.5 text-accent-primary group-hover:underline">
                {Icon && <Icon className="w-3.5 h-3.5" />}
                <span className="truncate">{primary}</span>
            </div>
            {sub && <div className="text-text-secondary text-xs mt-0.5 truncate">{sub}</div>}
            {id && <div className="text-text-tertiary text-[10px] font-mono mt-0.5 truncate">{id}</div>}
        </Link>
    );
}

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
