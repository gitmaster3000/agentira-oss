import React from 'react';
import { Link } from 'react-router-dom';
import { ROUTES } from '../../routes';
import {
    Clock,
    ExternalLink,
    Bot,
    Zap,
    DollarSign,
    AlertTriangle,
    Play,
} from 'lucide-react';

// Minimal run-status palette — mirrors RunDetail's STATUS_CONFIG for the
// states a task's single run actually reaches. Local so TaskPage doesn't
// depend on RunDetail's internals.
export const RUN_STATUS = {
    ready:        { bg: '#3b82f6', label: 'Ready' },
    pending:      { bg: '#5f6368', label: 'Queued' },
    running:      { bg: '#f1c40f', label: 'Running' },
    interrupting: { bg: '#9aa0a6', label: 'Stopping…' },
    paused:       { bg: '#9aa0a6', label: 'Paused' },
    completed:    { bg: '#2ecc71', label: 'Completed' },
    failed:       { bg: '#e74c3c', label: 'Failed' },
    cancelled:    { bg: '#9aa0a6', label: 'Cancelled' },
};

export const ACTIVE_RUN_STATUSES = new Set(['pending', 'running', 'interrupting']);

// 1 task = 1 run: the "current" run is simply the newest one.
export function pickCurrentRun(runs) {
    if (!Array.isArray(runs) || runs.length === 0) return null;
    return [...runs].sort(
        (a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0)
    )[0];
}

// When did Run.summary last change? While running it rolls every turn, so we
// stamp "now" on each change. First sighting of an already-finished run uses
// the run's own finish/create time instead of the moment we loaded the page.
export function summaryStamp(prevSummary, run, prevStamp, now) {
    if (!run || !run.summary) return null;
    if (run.summary === prevSummary) return prevStamp;
    if (prevSummary === null && run.status !== 'running') {
        return run.finished_at || run.created_at || now;
    }
    return now;
}

function formatDuration(ms) {
    if (ms == null) return '—';
    const s = Math.round(ms / 1000);
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    return `${m}m ${s % 60}s`;
}

function relTime(value) {
    if (!value) return '';
    const d = new Date(value);
    const diff = Math.round((Date.now() - d.getTime()) / 1000);
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return d.toLocaleString();
}

export function AgentSection({ run, runStatus, runActive, summaryUpdatedAt, task, canRunWithAgent, scheduling, handleRunWithAgent }) {
    const launcher = !canRunWithAgent ? null : (
        <RunLauncher
            scheduling={scheduling}
            handleRunWithAgent={handleRunWithAgent}
            label={run ? 'Run again with agent' : 'Run with agent'}
        />
    );

    if (!run) {
        return (
            <div className="bg-bg-card border border-border-subtle rounded-xl p-5 shadow-sm flex items-center gap-4">
                <Bot className="w-8 h-8 text-text-tertiary flex-shrink-0" />
                <div className="flex-1 min-w-0">
                    <p className="text-sm text-text-secondary">No agent run yet for this task.</p>
                    <p className="text-xs text-text-tertiary mt-0.5">{canRunWithAgent ? 'Kick one off, or wait for an agent to pick it up.' : 'Assign a managed agent to run this task.'}</p>
                </div>
                {launcher && <div className="flex-shrink-0">{launcher}</div>}
            </div>
        );
    }
    const totalTokens = (run.input_tokens || 0) + (run.output_tokens || 0);
    return (
        <div className="max-w-3xl space-y-6">
            {!runActive && launcher}
            {/* Run header */}
            <div className="flex items-center gap-3">
                <Link to={ROUTES.FORGE_RUN(run.id)} className="text-lg font-bold text-text-primary hover:text-accent-primary">
                    Run {run.id}
                </Link>
                {runStatus && (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-semibold text-white" style={{ backgroundColor: runStatus.bg }}>
                        {runActive && (
                            <span className="relative flex h-2 w-2">
                                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white opacity-75" />
                                <span className="relative inline-flex rounded-full h-2 w-2 bg-white" />
                            </span>
                        )}
                        {runStatus.label}
                    </span>
                )}
                {run.agent_name && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-bg-hover text-xs text-text-secondary">
                        <Bot className="w-3 h-3" /> {run.agent_name}
                    </span>
                )}
                <Link to={ROUTES.FORGE_RUN(run.id)} className="ml-auto text-xs text-accent-primary hover:underline flex items-center gap-1">
                    Full run <ExternalLink className="w-3 h-3" />
                </Link>
            </div>

            {/* Rolling summary — updates each turn while running. */}
            <div className="bg-bg-card border border-border-subtle border-l-4 rounded-lg p-5 shadow-sm" style={{ borderLeftColor: runStatus?.bg }}>
                <div className="flex items-center justify-between mb-2">
                    <h3 className="text-xs font-bold uppercase text-text-tertiary">Summary</h3>
                    {summaryUpdatedAt && (
                        <span className="text-[11px] text-text-tertiary flex items-center gap-1" title={new Date(summaryUpdatedAt).toLocaleString()}>
                            <Clock className="w-3 h-3" /> updated {relTime(summaryUpdatedAt)}
                        </span>
                    )}
                </div>
                {run.summary
                    ? <p className="text-sm text-text-primary whitespace-pre-wrap">{run.summary}</p>
                    : <p className="text-sm text-text-tertiary italic">{runActive ? 'Working…' : 'No summary yet.'}</p>}
            </div>

            {run.error && (
                <div className="bg-red-500/5 border border-red-500/20 rounded-lg p-4">
                    <div className="flex items-start gap-3">
                        <AlertTriangle className="w-5 h-5 text-red-400 mt-0.5 flex-shrink-0" />
                        <pre className="text-xs text-text-secondary whitespace-pre-wrap font-mono">{run.error}</pre>
                    </div>
                </div>
            )}

            {/* Artifacts */}
            {Array.isArray(run.artifacts) && run.artifacts.length > 0 && (
                <div className="bg-bg-card border border-border-subtle rounded-lg p-5 shadow-sm">
                    <h3 className="text-xs font-bold uppercase text-text-tertiary mb-3">Artifacts</h3>
                    <div className="space-y-1.5">
                        {run.artifacts.map((a, i) => (
                            <a key={i} href={a.url} target="_blank" rel="noopener noreferrer"
                               className="flex items-center gap-2 text-sm text-accent-primary hover:underline">
                                <ExternalLink className="w-3.5 h-3.5 flex-shrink-0" />
                                {a.label || a.url}
                            </a>
                        ))}
                    </div>
                </div>
            )}

            {/* Metrics */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <Metric icon={Clock} label="Duration" value={formatDuration(run.duration_ms)} />
                <Metric icon={Zap} label="Tokens" value={totalTokens > 0 ? totalTokens.toLocaleString() : '—'} />
                <Metric icon={DollarSign} label="Cost" value={run.cost_usd > 0 ? `$${run.cost_usd.toFixed(4)}` : '—'} />
                <Metric icon={Bot} label="Model" value={run.model_used || '—'} />
            </div>
        </div>
    );
}

function RunLauncher({ scheduling, handleRunWithAgent, label }) {
    return (
        <div className="flex justify-end">
            <button
                disabled={scheduling}
                onClick={handleRunWithAgent}
                className="text-xs px-3 py-1.5 rounded-lg bg-accent-subtle text-accent-primary hover:bg-accent-subtle/80 inline-flex items-center gap-1.5 transition-colors disabled:opacity-50"
            >
                <Play className="w-3 h-3" /> {label}
            </button>
        </div>
    );
}

function Metric({ icon: Icon, label, value }) {
    return (
        <div className="bg-bg-card border border-border-subtle rounded-lg p-4 shadow-sm">
            <div className="flex items-center gap-1.5 text-text-tertiary mb-1">
                <Icon className="w-3.5 h-3.5" />
                <span className="text-[10px] font-bold uppercase">{label}</span>
            </div>
            <div className="text-sm font-semibold text-text-primary truncate" title={value}>{value}</div>
        </div>
    );
}
