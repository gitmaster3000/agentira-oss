import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Play, RefreshCw, Clock, Bot, Zap, ChevronLeft, ChevronRight, Filter, DollarSign } from 'lucide-react';
import { api } from '../../api';

const STATUS_STYLES = {
    queued:        { bg: '#5f6368', label: 'Queued' },
    pending:       { bg: '#5f6368', label: 'Pending' },
    running:       { bg: '#f1c40f', label: 'Running' },
    waiting_human: { bg: '#ff9800', label: 'Waiting' },
    blocked:       { bg: '#e91e63', label: 'Blocked' },
    completed:     { bg: '#2ecc71', label: 'Completed' },
    failed:        { bg: '#e74c3c', label: 'Failed' },
    cancelled:     { bg: '#9aa0a6', label: 'Cancelled' },
};

const PAGE_SIZE = 25;

export function RunsDashboard() {
    const navigate = useNavigate();
    const [runs, setRuns] = useState([]);
    const [agents, setAgents] = useState([]);
    const [loading, setLoading] = useState(true);
    const [filters, setFilters] = useState({ status: '', agent_id: '' });
    const [page, setPage] = useState(0);

    const loadRuns = async () => {
        try {
            const params = {
                limit: PAGE_SIZE,
                offset: page * PAGE_SIZE,
            };
            if (filters.status) params.status = filters.status;
            if (filters.agent_id) params.agent_id = filters.agent_id;
            const data = await api.forge.listRuns(params);
            setRuns(data);
        } catch (err) {
            console.error('Failed to load runs:', err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        api.forge.listAgents().then(setAgents).catch(console.error);
    }, []);

    useEffect(() => {
        setLoading(true);
        loadRuns();
        const interval = setInterval(loadRuns, 8000);
        return () => clearInterval(interval);
    }, [filters, page]);

    return (
        <div className="flex-1 p-6 space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold text-text-primary">Runs</h1>
                    <p className="text-sm text-text-secondary mt-1">Execution history across all agents</p>
                </div>
                <button onClick={loadRuns} className="btn btn-ghost" title="Refresh">
                    <RefreshCw className="w-4 h-4" />
                </button>
            </div>

            {/* Filters */}
            <div className="flex items-center gap-3">
                <Filter className="w-4 h-4 text-text-tertiary" />
                <select
                    value={filters.status}
                    onChange={(e) => { setFilters({ ...filters, status: e.target.value }); setPage(0); }}
                    className="input py-1.5 px-3 text-sm w-auto"
                >
                    <option value="">All statuses</option>
                    <option value="queued">Queued</option>
                    <option value="running">Running</option>
                    <option value="waiting_human">Waiting (Human)</option>
                    <option value="blocked">Blocked</option>
                    <option value="completed">Completed</option>
                    <option value="failed">Failed</option>
                    <option value="cancelled">Cancelled</option>
                </select>
                <select
                    value={filters.agent_id}
                    onChange={(e) => { setFilters({ ...filters, agent_id: e.target.value }); setPage(0); }}
                    className="input py-1.5 px-3 text-sm w-auto"
                >
                    <option value="">All agents</option>
                    {agents.map((a) => (
                        <option key={a.id} value={a.id}>{a.name}</option>
                    ))}
                </select>
            </div>

            {/* Table */}
            {loading && runs.length === 0 ? (
                <div className="flex-1 flex items-center justify-center text-text-tertiary py-20">
                    Loading runs...
                </div>
            ) : runs.length === 0 ? (
                <div className="card text-center py-16">
                    <Play className="w-12 h-12 mx-auto mb-4 text-text-tertiary opacity-50" />
                    <h3 className="text-lg font-semibold text-text-primary mb-2">No runs found</h3>
                    <p className="text-sm text-text-secondary">
                        {filters.status || filters.agent_id
                            ? 'Try adjusting your filters.'
                            : 'Runs will appear here when agents start executing tasks.'}
                    </p>
                </div>
            ) : (
                <>
                    <div className="card p-0 overflow-hidden">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="border-b border-border-subtle text-text-tertiary text-xs uppercase">
                                    <th className="text-left px-4 py-3 font-medium">Status</th>
                                    <th className="text-left px-4 py-3 font-medium">Agent</th>
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
                                {runs.map((run) => (
                                    <RunRow key={run.id} run={run} navigate={navigate} />
                                ))}
                            </tbody>
                        </table>
                    </div>

                    {/* Pagination */}
                    <div className="flex items-center justify-between text-sm">
                        <div className="text-text-tertiary">
                            Page {page + 1}
                        </div>
                        <div className="flex items-center gap-2">
                            <button
                                onClick={() => setPage(Math.max(0, page - 1))}
                                disabled={page === 0}
                                className="btn btn-ghost py-1 px-2 disabled:opacity-30"
                            >
                                <ChevronLeft className="w-4 h-4" /> Prev
                            </button>
                            <button
                                onClick={() => setPage(page + 1)}
                                disabled={runs.length < PAGE_SIZE}
                                className="btn btn-ghost py-1 px-2 disabled:opacity-30"
                            >
                                Next <ChevronRight className="w-4 h-4" />
                            </button>
                        </div>
                    </div>
                </>
            )}
        </div>
    );
}

function RunRow({ run, navigate }) {
    const s = STATUS_STYLES[run.status] || STATUS_STYLES.pending;
    const totalTokens = (run.input_tokens || 0) + (run.output_tokens || 0);

    return (
        <tr className="border-b border-border-subtle hover:bg-bg-hover transition-colors cursor-pointer" onClick={() => navigate(`/forge/runs/${run.id}`)}>
            <td className="px-4 py-3">
                <span
                    className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium text-white"
                    style={{ backgroundColor: s.bg }}
                >
                    {s.label}
                </span>
            </td>
            <td className="px-4 py-3">
                <div className="flex items-center gap-2">
                    <Bot className="w-3.5 h-3.5 text-text-tertiary" />
                    <span className="text-text-primary">{run.agent_name || '—'}</span>
                </div>
            </td>
            <td className="px-4 py-3 text-text-secondary max-w-[200px] truncate" title={run.task_title}>
                {run.task_title || '—'}
            </td>
            <td className="px-4 py-3">
                {run.trigger_event ? (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-bg-hover text-xs text-text-secondary">
                        <Zap className="w-3 h-3" />
                        {run.trigger_event}
                    </span>
                ) : '—'}
            </td>
            <td className="px-4 py-3 text-text-tertiary text-xs truncate max-w-[120px]" title={run.model_used}>
                {run.model_used || '—'}
            </td>
            <td className="px-4 py-3 text-right text-text-secondary">
                {run.duration_ms != null ? formatDuration(run.duration_ms) : '—'}
            </td>
            <td className="px-4 py-3 text-right text-text-secondary">
                {totalTokens > 0 ? totalTokens.toLocaleString() : '—'}
            </td>
            <td className="px-4 py-3 text-right text-text-secondary">
                {run.cost_usd > 0 ? `$${run.cost_usd.toFixed(4)}` : '—'}
            </td>
            <td className="px-4 py-3 text-right text-text-tertiary text-xs whitespace-nowrap">
                {timeAgo(run.created_at)}
            </td>
        </tr>
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
