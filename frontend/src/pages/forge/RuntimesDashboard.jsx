import React, { useState, useEffect } from 'react';
import { Cpu, Wifi, WifiOff, Loader, Clock, Server } from 'lucide-react';
import { api } from '../../api';

const STATUS_STYLES = {
    online:  { color: '#2ecc71', icon: Wifi, label: 'Online' },
    offline: { color: '#5f6368', icon: WifiOff, label: 'Offline' },
    busy:    { color: '#f1c40f', icon: Loader, label: 'Busy' },
    unknown: { color: '#5f6368', icon: WifiOff, label: 'Unknown' },
};

export function RuntimesDashboard() {
    const [runtimes, setRuntimes] = useState([]);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState('all');

    const load = async () => {
        try {
            const statusParam = filter === 'all' ? undefined : { status: filter };
            const data = await api.forge.listRuntimes(statusParam);
            setRuntimes(data);
        } catch (err) {
            console.error('Failed to load runtimes:', err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        load();
        const t = setInterval(load, 10000);
        return () => clearInterval(t);
    }, [filter]);

    const grouped = runtimes.reduce((acc, rt) => {
        const key = `${rt.daemon_id}|${rt.device_name || 'local'}`;
        (acc[key] = acc[key] || []).push(rt);
        return acc;
    }, {});

    return (
        <div className="flex-1 p-6 space-y-6">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold text-text-primary">Runtimes</h1>
                    <p className="text-sm text-text-secondary mt-1">
                        {runtimes.length} runtime{runtimes.length !== 1 ? 's' : ''} registered across {Object.keys(grouped).length} daemon{Object.keys(grouped).length !== 1 ? 's' : ''}
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
                </div>
            </div>

            {loading ? (
                <div className="flex-1 flex items-center justify-center text-text-tertiary py-20">
                    Loading runtimes...
                </div>
            ) : runtimes.length === 0 ? (
                <EmptyState />
            ) : (
                <div className="space-y-6">
                    {Object.entries(grouped).map(([key, list]) => {
                        const [daemonId, deviceName] = key.split('|');
                        return (
                            <div key={key} className="space-y-2">
                                <div className="flex items-center gap-2 text-xs font-semibold text-text-tertiary uppercase tracking-wider">
                                    <Server className="w-3.5 h-3.5" />
                                    <span>{deviceName}</span>
                                    <span className="text-text-tertiary normal-case font-normal">· {daemonId.slice(0, 8)}</span>
                                </div>
                                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                                    {list.map(rt => <RuntimeCard key={rt.id} runtime={rt} />)}
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

function RuntimeCard({ runtime }) {
    const status = STATUS_STYLES[runtime.status] || STATUS_STYLES.unknown;
    const StatusIcon = status.icon;
    let caps = [];
    try { caps = JSON.parse(runtime.capabilities || '[]'); } catch { caps = []; }

    return (
        <div className="card hover:border-border-active transition-colors">
            <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-bg-hover flex items-center justify-center">
                        <Cpu className="w-5 h-5 text-text-secondary" />
                    </div>
                    <div>
                        <div className="text-sm font-semibold text-text-primary">{runtime.provider}</div>
                        {runtime.version && (
                            <div className="text-xs text-text-tertiary truncate max-w-[200px]" title={runtime.version}>
                                {runtime.version}
                            </div>
                        )}
                    </div>
                </div>
                <span
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium"
                    style={{ backgroundColor: status.color + '20', color: status.color }}
                >
                    <StatusIcon className="w-3 h-3" />
                    {status.label}
                </span>
            </div>

            {caps.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mb-3">
                    {caps.map(c => (
                        <span key={c} className="px-2 py-0.5 rounded bg-bg-hover text-[10px] text-text-secondary">
                            {c}
                        </span>
                    ))}
                </div>
            )}

            <div className="text-xs text-text-tertiary truncate mb-2" title={runtime.binary_path}>
                {runtime.binary_path}
            </div>

            {runtime.last_heartbeat && (
                <div className="flex items-center gap-1 text-xs text-text-tertiary border-t border-border-subtle pt-3">
                    <Clock className="w-3 h-3" /> {timeAgo(runtime.last_heartbeat)}
                </div>
            )}
        </div>
    );
}

function EmptyState() {
    return (
        <div className="card text-center py-16">
            <Cpu className="w-12 h-12 mx-auto mb-4 text-text-tertiary opacity-50" />
            <h3 className="text-lg font-semibold text-text-primary mb-2">No runtimes registered</h3>
            <p className="text-sm text-text-secondary max-w-md mx-auto">
                Install the AgentIRA CLI on a host machine and run <code className="px-1.5 py-0.5 rounded bg-bg-hover text-xs font-mono text-text-primary">agentira daemon start</code> to register local runtimes.
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
