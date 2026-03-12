import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Bot, Play, DollarSign, Zap, CheckCircle, XCircle, Clock, Activity } from 'lucide-react';
import { api } from '../../api';

function StatCard({ icon: Icon, label, value, sub, color }) {
    return (
        <div className="card flex items-start gap-4">
            <div
                className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0"
                style={{ backgroundColor: color + '18' }}
            >
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

export function ForgeOverview() {
    const [stats, setStats] = useState(null);
    const [recentRuns, setRecentRuns] = useState([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const load = async () => {
            try {
                const [s, runs] = await Promise.all([
                    api.forge.getStats(),
                    api.forge.listRuns({ limit: 8 }),
                ]);
                setStats(s);
                setRecentRuns(runs);
            } catch (err) {
                console.error('Failed to load forge stats:', err);
            } finally {
                setLoading(false);
            }
        };
        load();
        const interval = setInterval(load, 10000);
        return () => clearInterval(interval);
    }, []);

    if (loading) {
        return (
            <div className="flex-1 flex items-center justify-center text-text-tertiary">
                Loading Forge...
            </div>
        );
    }

    if (!stats) {
        return (
            <div className="flex-1 flex items-center justify-center text-text-tertiary">
                Failed to load stats
            </div>
        );
    }

    return (
        <div className="flex-1 p-6 space-y-6">
            <div>
                <h1 className="text-2xl font-bold text-text-primary">Forge</h1>
                <p className="text-sm text-text-secondary mt-1">Agent orchestration and execution tracking</p>
            </div>

            {/* Stats Grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <StatCard
                    icon={Bot}
                    label="Total Agents"
                    value={stats.agents.total}
                    sub={`${stats.agents.online} online, ${stats.agents.busy} busy`}
                    color="#00bcd4"
                />
                <StatCard
                    icon={Play}
                    label="Total Runs"
                    value={stats.runs.total}
                    sub={`${stats.runs.running} running now`}
                    color="#7c4dff"
                />
                <StatCard
                    icon={CheckCircle}
                    label="Success Rate"
                    value={`${stats.runs.success_rate}%`}
                    sub={`${stats.runs.completed} completed, ${stats.runs.failed} failed`}
                    color="#2ecc71"
                />
                <StatCard
                    icon={DollarSign}
                    label="Total Cost"
                    value={`$${stats.cost.total_usd.toFixed(2)}`}
                    sub={`${(stats.tokens.input + stats.tokens.output).toLocaleString()} tokens`}
                    color="#f1c40f"
                />
            </div>

            {/* Recent Runs */}
            <div className="card">
                <div className="flex items-center justify-between mb-4">
                    <h2 className="text-lg font-semibold text-text-primary">Recent Runs</h2>
                    <Link to="/forge/runs" className="text-sm text-accent-primary hover:text-accent-hover transition-colors">
                        View all
                    </Link>
                </div>

                {recentRuns.length === 0 ? (
                    <div className="text-center py-8 text-text-tertiary">
                        <Activity className="w-8 h-8 mx-auto mb-2 opacity-50" />
                        <p>No runs yet. Runs will appear here when agents execute tasks.</p>
                    </div>
                ) : (
                    <div className="space-y-2">
                        {recentRuns.map((run) => (
                            <div key={run.id} className="flex items-center gap-3 px-3 py-2 rounded-md hover:bg-bg-hover transition-colors">
                                <RunStatusBadge status={run.status} />
                                <div className="flex-1 min-w-0">
                                    <span className="text-sm text-text-primary font-medium">
                                        {run.agent_name || 'Unknown agent'}
                                    </span>
                                    {run.task_title && (
                                        <span className="text-sm text-text-tertiary ml-2">
                                            — {run.task_title}
                                        </span>
                                    )}
                                </div>
                                <div className="text-xs text-text-tertiary whitespace-nowrap">
                                    {run.trigger_event || 'manual'}
                                </div>
                                {run.duration_ms != null && (
                                    <div className="text-xs text-text-tertiary flex items-center gap-1">
                                        <Clock className="w-3 h-3" />
                                        {formatDuration(run.duration_ms)}
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}

function RunStatusBadge({ status }) {
    const styles = {
        pending:   { bg: '#5f6368', label: 'Pending' },
        running:   { bg: '#f1c40f', label: 'Running' },
        completed: { bg: '#2ecc71', label: 'Done' },
        failed:    { bg: '#e74c3c', label: 'Failed' },
        cancelled: { bg: '#9aa0a6', label: 'Cancelled' },
    };
    const s = styles[status] || styles.pending;
    return (
        <span
            className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium text-white"
            style={{ backgroundColor: s.bg }}
        >
            {s.label}
        </span>
    );
}

function formatDuration(ms) {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
}
