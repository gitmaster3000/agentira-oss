import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bot, RefreshCw, Wifi, WifiOff, Loader, Trash2, Clock, Play, DollarSign, Cpu, Plus } from 'lucide-react';
import { api } from '../../api';
import { CreateAgentModal } from '../../components/CreateAgentModal';

const STATUS_STYLES = {
    online:  { color: '#2ecc71', icon: Wifi, label: 'Online' },
    offline: { color: '#5f6368', icon: WifiOff, label: 'Offline' },
    busy:    { color: '#f1c40f', icon: Loader, label: 'Busy' },
};

export function AgentsDashboard() {
    const navigate = useNavigate();
    const [agents, setAgents] = useState([]);
    const [runtimes, setRuntimes] = useState([]);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState('all');
    const [showCreate, setShowCreate] = useState(false);

    const loadAgents = async () => {
        try {
            const statusParam = filter === 'all' ? undefined : filter;
            const data = await api.forge.listAgents(statusParam);
            // Defensive: Forge only surfaces managed agents (backend already
            // filters, but belt-and-suspenders if any service-account row leaks).
            setAgents((Array.isArray(data) ? data : []).filter(a => a.runtime_id));
        } catch (err) {
            console.error('Failed to load agents:', err);
        } finally {
            setLoading(false);
        }
    };

    const loadRuntimes = async () => {
        try {
            const data = await api.forge.listRuntimes();
            setRuntimes(data);
        } catch (err) {
            console.error('Failed to load runtimes:', err);
        }
    };

    useEffect(() => {
        loadAgents();
        loadRuntimes();
        const interval = setInterval(() => { loadAgents(); loadRuntimes(); }, 10000);
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
                    <button
                        onClick={() => setShowCreate(true)}
                        className="btn btn-primary text-xs"
                    >
                        <Plus className="w-4 h-4" /> New Agent
                    </button>
                </div>
            </div>

            {/* Local Runtimes */}
            {runtimes.length > 0 && (
                <div className="space-y-2">
                    <div className="text-xs font-semibold text-text-tertiary uppercase tracking-wider flex items-center gap-2">
                        <Cpu className="w-3.5 h-3.5" /> Local Runtimes
                    </div>
                    <div className="flex flex-wrap gap-2">
                        {runtimes.map((rt) => (
                            <div key={rt.id} className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-bg-hover border border-border-subtle text-xs">
                                <span className={`w-1.5 h-1.5 rounded-full ${rt.status === 'online' ? 'bg-emerald-400' : 'bg-text-tertiary'}`} />
                                <span className="font-medium text-text-primary">{rt.provider}</span>
                                {rt.version && <span className="text-text-tertiary">{rt.version.split(' ')[0]}</span>}
                                <span className="text-text-tertiary">· {rt.device_name || 'local'}</span>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Agent Grid */}
            {loading ? (
                <div className="flex-1 flex items-center justify-center text-text-tertiary py-20">
                    Loading agents...
                </div>
            ) : filtered.length === 0 ? (
                <EmptyState />
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                    {filtered.map((agent) => (
                        <AgentCard key={agent.id} agent={agent} onDelete={() => handleDelete(agent.id)} onClick={() => navigate(`/forge/agents/${agent.id}`)} onRefresh={loadAgents} />
                    ))}
                </div>
            )}

            {showCreate && (
                <CreateAgentModal
                    onClose={() => setShowCreate(false)}
                    onSuccess={() => { setShowCreate(false); loadAgents(); }}
                />
            )}
        </div>
    );
}

function AgentCard({ agent, onDelete, onClick, onRefresh }) {
    const status = STATUS_STYLES[agent.status] || STATUS_STYLES.offline;
    const StatusIcon = status.icon;

    return (
        <div className="card hover:border-border-active transition-colors group cursor-pointer" onClick={onClick}>
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
                    {agent.status === 'busy' && (
                        <button
                            onClick={async (e) => {
                                e.stopPropagation();
                                try {
                                    await api.forge.resetAgentStatus(agent.id);
                                    if (onRefresh) onRefresh();
                                } catch (err) {
                                    console.error('Reset failed:', err);
                                }
                            }}
                            className="p-1 rounded hover:bg-yellow-500/20 text-yellow-400 transition-all"
                            title="Reset — unstick busy status"
                        >
                            <RefreshCw className="w-3.5 h-3.5" />
                        </button>
                    )}
                    <button
                        onClick={(e) => { e.stopPropagation(); onDelete(); }}
                        className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-red-500/10 text-text-tertiary hover:text-red-400 transition-all"
                        title="Delete agent"
                    >
                        <Trash2 className="w-3.5 h-3.5" />
                    </button>
                </div>
            </div>

            {/* Config row */}
            <div className="flex flex-wrap gap-2 mb-3">
                {agent.model && (
                    <span className="px-2 py-0.5 rounded bg-bg-hover text-xs text-text-secondary truncate max-w-[220px]" title={agent.model}>
                        {agent.model}
                    </span>
                )}
                {agent.runtime_id && agent.runtime_provider && (
                    <span
                        className="px-2 py-0.5 rounded bg-emerald-500/15 text-xs text-emerald-400 flex items-center gap-1"
                        title={agent.runtime_version || agent.runtime_provider}
                    >
                        <Cpu className="w-3 h-3" /> {agent.runtime_provider}
                    </span>
                )}
            </div>

            {/* Webhook */}
            {agent.webhook_url && (
                <div className="text-xs text-text-tertiary truncate mb-2" title={agent.webhook_url}>
                    {agent.webhook_url}
                </div>
            )}

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

function EmptyState() {
    return (
        <div className="card text-center py-16">
            <Bot className="w-12 h-12 mx-auto mb-4 text-text-tertiary opacity-50" />
            <h3 className="text-lg font-semibold text-text-primary mb-2">No agents found</h3>
            <p className="text-sm text-text-secondary mb-2 max-w-md mx-auto">
                Agents are auto-synced from bot profiles. Create a service account in Settings to add an agent.
            </p>
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
