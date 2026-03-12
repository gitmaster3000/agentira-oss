import React, { useState, useEffect } from 'react';
import { Bot, Plus, RefreshCw, Wifi, WifiOff, Loader, Trash2, ChevronDown, Clock, Play, DollarSign } from 'lucide-react';
import { api } from '../../api';

const STATUS_STYLES = {
    online:  { color: '#2ecc71', icon: Wifi, label: 'Online' },
    offline: { color: '#5f6368', icon: WifiOff, label: 'Offline' },
    busy:    { color: '#f1c40f', icon: Loader, label: 'Busy' },
};

export function AgentsDashboard() {
    const [agents, setAgents] = useState([]);
    const [profiles, setProfiles] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showCreate, setShowCreate] = useState(false);
    const [filter, setFilter] = useState('all');

    const loadAgents = async () => {
        try {
            const statusParam = filter === 'all' ? undefined : filter;
            const data = await api.forge.listAgents(statusParam);
            setAgents(data);
        } catch (err) {
            console.error('Failed to load agents:', err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadAgents();
        const interval = setInterval(loadAgents, 10000);
        return () => clearInterval(interval);
    }, [filter]);

    const handleDelete = async (id) => {
        if (!confirm('Delete this agent? All associated runs will also be deleted.')) return;
        try {
            await api.forge.deleteAgent(id);
            loadAgents();
        } catch (err) {
            console.error('Failed to delete agent:', err);
        }
    };

    const filtered = agents;

    return (
        <div className="flex-1 p-6 space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold text-text-primary">Agents</h1>
                    <p className="text-sm text-text-secondary mt-1">
                        {agents.length} agent{agents.length !== 1 ? 's' : ''} registered
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <select
                        value={filter}
                        onChange={(e) => setFilter(e.target.value)}
                        className="input py-1.5 px-3 text-sm w-auto"
                    >
                        <option value="all">All statuses</option>
                        <option value="online">Online</option>
                        <option value="offline">Offline</option>
                        <option value="busy">Busy</option>
                    </select>
                    <button onClick={loadAgents} className="btn btn-ghost" title="Refresh">
                        <RefreshCw className="w-4 h-4" />
                    </button>
                    <button onClick={() => setShowCreate(true)} className="btn btn-primary">
                        <Plus className="w-4 h-4" /> Register Agent
                    </button>
                </div>
            </div>

            {/* Agent Grid */}
            {loading ? (
                <div className="flex-1 flex items-center justify-center text-text-tertiary py-20">
                    Loading agents...
                </div>
            ) : filtered.length === 0 ? (
                <EmptyState onRegister={() => setShowCreate(true)} />
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                    {filtered.map((agent) => (
                        <AgentCard key={agent.id} agent={agent} onDelete={() => handleDelete(agent.id)} />
                    ))}
                </div>
            )}

            {/* Create Modal */}
            {showCreate && (
                <CreateAgentModal
                    onClose={() => setShowCreate(false)}
                    onCreated={() => { setShowCreate(false); loadAgents(); }}
                />
            )}
        </div>
    );
}

function AgentCard({ agent, onDelete }) {
    const status = STATUS_STYLES[agent.status] || STATUS_STYLES.offline;
    const StatusIcon = status.icon;

    return (
        <div className="card hover:border-border-active transition-colors group">
            <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-bg-hover flex items-center justify-center">
                        <Bot className="w-5 h-5 text-text-secondary" />
                    </div>
                    <div>
                        <div className="text-sm font-semibold text-text-primary">{agent.name}</div>
                        <div className="text-xs text-text-tertiary">{agent.profile_name}</div>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <span
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium"
                        style={{ backgroundColor: status.color + '20', color: status.color }}
                    >
                        <StatusIcon className="w-3 h-3" />
                        {status.label}
                    </span>
                    <button
                        onClick={onDelete}
                        className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-red-500/10 text-text-tertiary hover:text-red-400 transition-all"
                        title="Delete agent"
                    >
                        <Trash2 className="w-3.5 h-3.5" />
                    </button>
                </div>
            </div>

            {/* Config row */}
            <div className="flex flex-wrap gap-2 mb-3">
                {agent.executor_type && (
                    <span className="px-2 py-0.5 rounded bg-bg-hover text-xs text-text-secondary">
                        {agent.executor_type}
                    </span>
                )}
                {agent.model && (
                    <span className="px-2 py-0.5 rounded bg-bg-hover text-xs text-text-secondary truncate max-w-[180px]" title={agent.model}>
                        {agent.model}
                    </span>
                )}
            </div>

            {/* Stats row */}
            <div className="flex items-center gap-4 text-xs text-text-tertiary border-t border-border-subtle pt-3">
                <span className="flex items-center gap-1">
                    <Play className="w-3 h-3" /> {agent.total_runs} runs
                </span>
                <span className="flex items-center gap-1">
                    <DollarSign className="w-3 h-3" /> ${agent.total_cost_usd.toFixed(2)}
                </span>
                {agent.last_heartbeat && (
                    <span className="flex items-center gap-1 ml-auto">
                        <Clock className="w-3 h-3" /> {timeAgo(agent.last_heartbeat)}
                    </span>
                )}
            </div>
        </div>
    );
}

function EmptyState({ onRegister }) {
    return (
        <div className="card text-center py-16">
            <Bot className="w-12 h-12 mx-auto mb-4 text-text-tertiary opacity-50" />
            <h3 className="text-lg font-semibold text-text-primary mb-2">No agents registered</h3>
            <p className="text-sm text-text-secondary mb-6 max-w-md mx-auto">
                Agents are runtime executors that pick up and run tasks. Register an agent to start tracking executions.
            </p>
            <button onClick={onRegister} className="btn btn-primary">
                <Plus className="w-4 h-4" /> Register First Agent
            </button>
        </div>
    );
}

function CreateAgentModal({ onClose, onCreated }) {
    const [profiles, setProfiles] = useState([]);
    const [form, setForm] = useState({
        profile_id: '',
        name: '',
        executor_type: 'http',
        model: '',
        webhook_url: '',
    });
    const [submitting, setSubmitting] = useState(false);

    useEffect(() => {
        api.getProfiles().then(setProfiles).catch(console.error);
    }, []);

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!form.profile_id || !form.name) return;
        setSubmitting(true);
        try {
            await api.forge.createAgent(form);
            onCreated();
        } catch (err) {
            console.error('Failed to create agent:', err);
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center animate-fade-in" onClick={onClose}>
            <div className="bg-bg-card border border-border-subtle rounded-lg w-full max-w-md p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
                <h2 className="text-lg font-semibold text-text-primary mb-4">Register Agent</h2>
                <form onSubmit={handleSubmit} className="space-y-4">
                    <div>
                        <label className="block text-sm text-text-secondary mb-1">Name</label>
                        <input
                            className="input"
                            placeholder="e.g. swe-agent-1"
                            value={form.name}
                            onChange={(e) => setForm({ ...form, name: e.target.value })}
                            required
                        />
                    </div>

                    <div>
                        <label className="block text-sm text-text-secondary mb-1">Profile (Identity)</label>
                        <select
                            className="input"
                            value={form.profile_id}
                            onChange={(e) => setForm({ ...form, profile_id: e.target.value })}
                            required
                        >
                            <option value="">Select a profile...</option>
                            {profiles.map((p) => (
                                <option key={p.id} value={p.id}>
                                    {p.display_name || p.name} ({p.role})
                                </option>
                            ))}
                        </select>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                        <div>
                            <label className="block text-sm text-text-secondary mb-1">Executor</label>
                            <select
                                className="input"
                                value={form.executor_type}
                                onChange={(e) => setForm({ ...form, executor_type: e.target.value })}
                            >
                                <option value="http">HTTP</option>
                                <option value="zeroclaw">ZeroClaw</option>
                                <option value="cli">CLI</option>
                            </select>
                        </div>
                        <div>
                            <label className="block text-sm text-text-secondary mb-1">Model</label>
                            <input
                                className="input"
                                placeholder="e.g. claude-sonnet-4-20250514"
                                value={form.model}
                                onChange={(e) => setForm({ ...form, model: e.target.value })}
                            />
                        </div>
                    </div>

                    <div>
                        <label className="block text-sm text-text-secondary mb-1">Webhook URL</label>
                        <input
                            className="input"
                            placeholder="http://localhost:9100/webhook"
                            value={form.webhook_url}
                            onChange={(e) => setForm({ ...form, webhook_url: e.target.value })}
                        />
                    </div>

                    <div className="flex justify-end gap-2 pt-2">
                        <button type="button" onClick={onClose} className="btn btn-ghost">Cancel</button>
                        <button type="submit" disabled={submitting} className="btn btn-primary">
                            {submitting ? 'Registering...' : 'Register Agent'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
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
