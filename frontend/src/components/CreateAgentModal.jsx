import React, { useState, useRef, useEffect, useMemo } from 'react';
import { Bot, X, Cpu } from 'lucide-react';
import { api } from '../api';

export function CreateAgentModal({ onClose, onSuccess }) {
    const [name, setName] = useState('');
    const [runtimeId, setRuntimeId] = useState('');
    const [profileId, setProfileId] = useState('');
    const [model, setModel] = useState('');
    const [customModel, setCustomModel] = useState('');
    const [homePath, setHomePath] = useState('');
    const [runtimes, setRuntimes] = useState([]);
    const [botProfiles, setBotProfiles] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const modalRef = useRef(null);

    useEffect(() => {
        api.forge.listRuntimes().catch(() => []).then(setRuntimes);
        api.getProfiles('bot').catch(() => []).then(setBotProfiles);
    }, []);

    const onlineRuntimes = useMemo(
        () => runtimes.filter(r => r.status === 'online'),
        [runtimes],
    );
    const selectedRuntime = useMemo(
        () => onlineRuntimes.find(r => r.id === runtimeId),
        [onlineRuntimes, runtimeId],
    );
    const runtimeModels = selectedRuntime?.models || [];

    // Default model when runtime changes
    useEffect(() => {
        if (!selectedRuntime) {
            setModel('');
            return;
        }
        setModel(runtimeModels[0] || '__custom__');
    }, [runtimeId]); // eslint-disable-line

    const effectiveModel = model === '__custom__' ? customModel.trim() : model;

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!name.trim() || !runtimeId) return;
        setLoading(true);
        setError('');
        try {
            const created = await api.forge.createAgent({
                name: name.trim(),
                runtime_id: runtimeId,
                model: effectiveModel,
                executor_type: 'cli',
                profile_id: profileId || null,
            });
            // home_path isn't part of the create endpoint yet — set it
            // immediately via update if user customized.
            if (homePath.trim() && created?.id) {
                try {
                    await api.forge.updateAgent(created.id, { home_path: homePath.trim() });
                } catch (err) {
                    console.warn('home_path set failed:', err);
                }
            }
            onSuccess?.();
            onClose();
        } catch (err) {
            setError(err.message || 'Failed to create agent');
        } finally {
            setLoading(false);
        }
    };

    const handleBackdropClick = (e) => {
        if (modalRef.current && !modalRef.current.contains(e.target)) onClose();
    };

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm animate-fade-in"
            onClick={handleBackdropClick}
        >
            <div
                ref={modalRef}
                className="w-full max-w-lg rounded-xl shadow-2xl overflow-hidden"
                style={{
                    backgroundColor: 'var(--bg-card)',
                    border: '1px solid var(--border-subtle)',
                }}
                onClick={e => e.stopPropagation()}
            >
                <div
                    className="px-6 py-5 flex items-center gap-3"
                    style={{ borderBottom: '1px solid var(--border-subtle)' }}
                >
                    <div
                        className="w-10 h-10 rounded-lg flex items-center justify-center shadow-lg flex-shrink-0"
                        style={{ backgroundColor: 'var(--accent-primary)' }}
                    >
                        <Bot className="w-5 h-5 text-white" />
                    </div>
                    <div className="flex-1">
                        <h3 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>
                            New Agent
                        </h3>
                        <p className="text-xs" style={{ color: 'var(--text-tertiary)' }}>
                            Pick a runtime and a model — that's the agent
                        </p>
                    </div>
                    <button
                        onClick={onClose}
                        className="p-1.5 rounded-xl transition-colors hover:bg-bg-hover"
                        style={{ color: 'var(--text-tertiary)' }}
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>

                <form onSubmit={handleSubmit} className="p-6 space-y-4 max-h-[70vh] overflow-y-auto custom-scrollbar">
                    <div>
                        <label className="block text-xs font-bold uppercase mb-1.5" style={{ color: 'var(--text-tertiary)', letterSpacing: '0.04em' }}>
                            Agent Name <span style={{ color: '#ef4444' }}>*</span>
                        </label>
                        <input
                            type="text"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            className="input"
                            placeholder="e.g. claude-coder"
                            autoFocus
                            required
                        />
                    </div>

                    <div>
                        <label className="block text-xs font-bold uppercase mb-1.5" style={{ color: 'var(--text-tertiary)', letterSpacing: '0.04em' }}>
                            Home folder <span className="font-normal lowercase">(optional)</span>
                        </label>
                        <p className="text-[11px] mb-2" style={{ color: 'var(--text-tertiary)' }}>
                            Where this agent lives on disk — its repo copies, memory, and scratch files. Leave empty to use the default.
                        </p>
                        <input
                            type="text"
                            value={homePath}
                            onChange={(e) => setHomePath(e.target.value)}
                            className="input"
                            placeholder="~/.agentira/agents/<auto>/home/"
                        />
                    </div>

                    {/* AP-86: bot↔agent merge. No "bot profile" picker — the agent's
                        backing profile is auto-created with the same id when you save. */}
                    <div>
                        <label className="block text-xs font-bold uppercase mb-1.5" style={{ color: 'var(--text-tertiary)', letterSpacing: '0.04em' }}>
                            Runtime <span style={{ color: '#ef4444' }}>*</span>
                        </label>
                        <p className="text-[11px] mb-2" style={{ color: 'var(--text-tertiary)' }}>
                            Required — Forge agents are dispatchable by definition. For API-key-only identities (CI, plugins, external sessions), use <strong>Settings → Service Accounts</strong> instead.
                        </p>
                        {onlineRuntimes.length === 0 ? (
                            <div
                                className="rounded-lg p-3 text-xs"
                                style={{
                                    border: '1px dashed var(--border-subtle)',
                                    backgroundColor: 'var(--bg-app)',
                                    color: 'var(--text-tertiary)',
                                }}
                            >
                                No online runtimes. Run <code className="px-1 py-0.5 rounded bg-bg-hover font-mono" style={{ color: 'var(--text-primary)' }}>agentira daemon start</code> on a host machine to register one.
                            </div>
                        ) : (
                            <div className="grid grid-cols-1 gap-1.5">
                                {onlineRuntimes.map(rt => (
                                    <button
                                        key={rt.id}
                                        type="button"
                                        onClick={() => setRuntimeId(rt.id)}
                                        className="px-3 py-2 rounded-lg text-xs font-medium transition-all border text-left flex items-center gap-2"
                                        style={runtimeId === rt.id ? {
                                            borderColor: 'var(--accent-primary)',
                                            color: 'var(--accent-primary)',
                                            backgroundColor: 'var(--accent-subtle)',
                                        } : {
                                            borderColor: 'var(--border-subtle)',
                                            color: 'var(--text-secondary)',
                                            backgroundColor: 'transparent',
                                        }}
                                    >
                                        <Cpu className="w-3.5 h-3.5 flex-shrink-0" />
                                        <span className="font-semibold">{rt.provider}</span>
                                        {rt.version && <span className="opacity-70 truncate">{rt.version.split(' ')[0]}</span>}
                                        <span className="opacity-50 ml-auto">· {rt.device_name || 'local'}</span>
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>

                    {selectedRuntime && (
                        <div>
                            <label className="block text-xs font-bold uppercase mb-1.5" style={{ color: 'var(--text-tertiary)', letterSpacing: '0.04em' }}>
                                Model
                            </label>
                            {runtimeModels.length > 0 ? (
                                <select
                                    value={model}
                                    onChange={(e) => setModel(e.target.value)}
                                    className="input"
                                >
                                    {runtimeModels.map(m => (
                                        <option key={m} value={m}>{m}</option>
                                    ))}
                                    <option value="__custom__">Custom…</option>
                                </select>
                            ) : (
                                <input
                                    type="text"
                                    value={customModel}
                                    onChange={(e) => { setCustomModel(e.target.value); setModel('__custom__'); }}
                                    className="input"
                                    placeholder="Model id (runtime did not advertise any)"
                                />
                            )}
                            {model === '__custom__' && runtimeModels.length > 0 && (
                                <input
                                    type="text"
                                    value={customModel}
                                    onChange={(e) => setCustomModel(e.target.value)}
                                    className="input mt-1.5"
                                    placeholder="Custom model id"
                                />
                            )}
                        </div>
                    )}

                    {error && (
                        <div className="text-xs px-3 py-2 rounded-lg" style={{
                            backgroundColor: 'rgba(239, 68, 68, 0.1)',
                            color: '#ef4444',
                            border: '1px solid rgba(239, 68, 68, 0.3)',
                        }}>
                            {error}
                        </div>
                    )}

                    <div className="flex justify-end gap-2 pt-3" style={{ borderTop: '1px solid var(--border-subtle)' }}>
                        <button type="button" onClick={onClose} className="btn btn-ghost">
                            Cancel
                        </button>
                        <button
                            type="submit"
                            disabled={loading || !name.trim() || !runtimeId}
                            className="btn btn-primary"
                        >
                            {loading ? 'Creating...' : 'Create Agent'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}
