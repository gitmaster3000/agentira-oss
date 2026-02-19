import React, { useState, useEffect, useRef } from 'react';
import { api } from '../api';
import { useAuth } from '../context/AuthContext';
import { useNavigate, useLocation } from 'react-router-dom';
import { Bot, Key, Lock, Trash2, Plus, Shield, Copy, Check, User, ChevronRight } from 'lucide-react';

export function Settings() {
    const { user } = useAuth();
    const navigate = useNavigate();
    const location = useLocation();
    const [activeTab, setActiveTab] = useState(location.state?.activeTab || 'general'); // 'general' or 'permissions'

    useEffect(() => {
        if (location.state?.activeTab) {
            setActiveTab(location.state.activeTab);
        }
    }, [location.state]);

    // Data states
    const [profiles, setProfiles] = useState([]);
    const [bots, setBots] = useState([]);
    const [me, setMe] = useState(null);
    const [roles, setRoles] = useState([]);
    const [allPermissions, setAllPermissions] = useState([]);
    const [securitySubTab, setSecuritySubTab] = useState('roles'); // 'roles' or 'permissions'
    const [searchQuery, setSearchQuery] = useState('');
    const [selectedRoleName, setSelectedRoleName] = useState(null);

    // UI states
    const [loading, setLoading] = useState(true);
    const [newBotKey, setNewBotKey] = useState(null);
    const [copied, setCopied] = useState(false);
    const [loadingConfig, setLoadingConfig] = useState(false);

    // Prompt/Confirmation states
    const [promptState, setPromptState] = useState(null); // { title: string, description: string, value: string, onConfirm: (val: string) => void }
    const [confirmState, setConfirmState] = useState(null); // { title: string, description: string, onConfirm: () => void }

    const isAdmin = user?.role === 'admin' || user?.role?.name === 'admin';

    useEffect(() => {
        if (!user) {
            navigate('/login');
            return;
        }
        loadGeneralData();
    }, [user, navigate]);

    useEffect(() => {
        if (activeTab === 'permissions' && isAdmin) {
            loadPermissionData();
        }
    }, [activeTab, isAdmin]);

    async function loadGeneralData() {
        setLoading(true);
        try {
            const meData = await api.getMe(user.name);
            setMe(meData);
        } catch (err) {
            console.error('Failed to load profile:', err);
        }

        try {
            const botsData = await api.listServiceAccounts();
            setBots(botsData);
        } catch (err) {
            console.error('Failed to load bots:', err);
        }

        if (isAdmin) {
            try {
                const profilesData = await api.getProfiles();
                setProfiles(profilesData);
            } catch (err) {
                console.error('Failed to load profiles:', err);
            }
        }
        setLoading(false);
    }

    async function loadPermissionData() {
        setLoading(true);
        try {
            const [rolesData, permsData] = await Promise.all([
                api.getRoles(),
                api.getPermissions()
            ]);
            setRoles(rolesData);
            setAllPermissions(permsData);
        } catch (err) {
            console.error('Failed to load RBAC data:', err);
        } finally {
            setLoading(false);
        }
    }

    async function togglePermission(roleName, codename, isGranted) {
        try {
            if (isGranted) {
                await api.revokePermission(roleName, codename);
            } else {
                await api.grantPermission(roleName, codename);
            }
            await loadPermissionData();
        } catch (err) {
            alert(err.message);
        }
    }

    // ... handleCreateBot, handleCopyKey, handleCopyConfig, handleDeleteBot, handleDeleteProfile unchanged ...
    async function handleCreateBot() {
        setPromptState({
            title: "Create New Bot",
            description: "Enter a name for your new service account:",
            value: "",
            onConfirm: async (name) => {
                if (!name) return;
                try {
                    const res = await api.createServiceAccount(name);
                    setNewBotKey({ name: res.name || name, api_key: res.api_key });
                    setCopied(false);
                    await loadGeneralData();
                } catch (err) {
                    alert(err.message);
                } finally {
                    setPromptState(null);
                }
            },
            onCancel: () => setPromptState(null)
        });
    }

    async function handleCopyKey() {
        if (!newBotKey) return;
        try {
            await navigator.clipboard.writeText(newBotKey.api_key);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch {
            const el = document.getElementById('api-key-display');
            if (el) { el.select(); document.execCommand('copy'); setCopied(true); setTimeout(() => setCopied(false), 2000); }
        }
    }

    async function handleCopyConfig(botId, botKey = null) {
        setLoadingConfig(true);
        try {
            let key = botKey;
            if (!key) {
                const botData = await api.getServiceAccount(botId);
                key = botData.api_key;
            }
            const hostname = window.location.hostname;
            const mcpUrl = `${window.location.protocol}//${hostname}:8000/sse`;
            const config = { agentira: { url: mcpUrl, headers: { Authorization: `Bearer ${key}` } } };
            await navigator.clipboard.writeText(JSON.stringify(config, null, 2));
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
            alert("MCP Configuration copied to clipboard!");
        } catch (err) {
            alert("Failed to copy config: " + err.message);
        } finally {
            setLoadingConfig(false);
        }
    }

    async function handleDeleteBot(id, name) {
        setConfirmState({
            title: "Delete Bot",
            description: `Are you sure you want to delete bot "${name}"? This cannot be undone.`,
            onConfirm: async () => {
                try {
                    await api.deleteServiceAccount(id);
                    await loadGeneralData();
                } catch (err) {
                    alert(err.message);
                } finally {
                    setConfirmState(null);
                }
            },
            onCancel: () => setConfirmState(null)
        });
    }

    async function handleDeleteProfile(id, name) {
        setConfirmState({
            title: "Delete Profile",
            description: `Are you sure you want to delete profile "${name}"?`,
            onConfirm: async () => {
                try {
                    await api.deleteProfile(id);
                    await loadGeneralData();
                } catch (err) {
                    alert(err.message);
                } finally {
                    setConfirmState(null);
                }
            },
            onCancel: () => setConfirmState(null)
        });
    }

    async function handleCreatePermission() {
        setPromptState({
            title: "Create Permission",
            description: "Enter permission codename (e.g. 'project:manage'):",
            value: "",
            onConfirm: async (codename) => {
                if (!codename) return;
                setPromptState({
                    title: "Permission Description",
                    description: `Enter description for '${codename}':`,
                    value: "",
                    onConfirm: async (description) => {
                        try {
                            await api.createPermission({ codename, description });
                            await loadPermissionData();
                        } catch (err) {
                            alert(err.message);
                        } finally {
                            setPromptState(null);
                        }
                    },
                    onCancel: () => setPromptState(null)
                });
            },
            onCancel: () => setPromptState(null)
        });
    }

    async function handleCreateRole() {
        setPromptState({
            title: "Create Role",
            description: "Enter role name (e.g. 'auditor'):",
            value: "",
            onConfirm: async (name) => {
                if (!name) return;
                setPromptState({
                    title: "Role Description",
                    description: `Enter description for role '${name}':`,
                    value: "",
                    onConfirm: async (description) => {
                        try {
                            await api.createRole({ name, description });
                            await loadPermissionData();
                        } catch (err) {
                            alert(err.message);
                        } finally {
                            setPromptState(null);
                        }
                    },
                    onCancel: () => setPromptState(null)
                });
            },
            onCancel: () => setPromptState(null)
        });
    }

    const roleBadge = (role) => ({
        backgroundColor: (role === 'agent' || role === 'bot') ? 'rgba(124,77,255,0.12)' : role === 'admin' ? 'rgba(239,68,68,0.12)' : 'rgba(46,204,113,0.12)',
        color: (role === 'agent' || role === 'bot') ? 'var(--accent-primary)' : role === 'admin' ? '#ef4444' : '#2ecc71',
    });

    if (loading && !me && !roles.length) {
        return <div className="p-8 text-center text-secondary">Loading...</div>;
    }

    return (
        <div className="flex flex-col h-full overflow-hidden">
            <header className="p-4 flex justify-between items-center" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                <div className="flex flex-col gap-1">
                    <h2 className="text-xl font-bold flex items-center gap-2">
                        <Lock className="w-5 h-5" /> Settings
                    </h2>

                    {isAdmin && (
                        <nav className="flex gap-4 mt-2">
                            <button
                                onClick={() => setActiveTab('general')}
                                className={`text-xs font-bold uppercase tracking-wider pb-1 border-b-2 transition-all ${activeTab === 'general' ? 'border-purple-500 text-purple-400' : 'border-transparent text-secondary hover:text-primary'}`}
                            >
                                General
                            </button>
                            <button
                                onClick={() => setActiveTab('permissions')}
                                className={`text-xs font-bold uppercase tracking-wider pb-1 border-b-2 transition-all ${activeTab === 'permissions' ? 'border-purple-500 text-purple-400' : 'border-transparent text-secondary hover:text-primary'}`}
                            >
                                Security
                            </button>
                        </nav>
                    )}
                </div>
            </header>

            <div className="flex-1 overflow-y-auto p-4">
                {activeTab === 'general' ? (
                    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-300">
                        {/* ── Your Profile ───────────────────────────────────────────── */}
                        {me && (
                            <section className="grid gap-3">
                                <h3 className="text-xs font-bold uppercase tracking-wider flex items-center gap-2" style={{ color: 'var(--text-tertiary)' }}>
                                    <User className="w-4 h-4" /> Your Profile
                                </h3>
                                <div className="p-4 rounded-lg border" style={{ backgroundColor: 'var(--bg-panel)', borderColor: 'var(--border-subtle)' }}>
                                    <div className="flex items-center gap-4">
                                        <div className="w-14 h-14 rounded-full flex items-center justify-center font-bold text-2xl" style={{ backgroundColor: 'var(--accent-subtle)', color: 'var(--accent-primary)' }}>
                                            {me.display_name?.[0]?.toUpperCase() || 'U'}
                                        </div>
                                        <div>
                                            <div className="font-semibold text-lg">{me.display_name}</div>
                                            <div className="text-xs font-mono" style={{ color: 'var(--text-tertiary)' }}>@{me.name}</div>
                                            <span className="text-[10px] px-2 py-0.5 rounded-full font-bold uppercase mt-1 inline-block" style={roleBadge(me.role)}>{me.role}</span>
                                        </div>
                                    </div>
                                </div>
                            </section>
                        )}

                        {/* ── Service Accounts / Bots ─────────────────────────────────── */}
                        <section className="grid gap-3">
                            <div className="flex items-center justify-between">
                                <h3 className="text-xs font-bold uppercase tracking-wider flex items-center gap-2" style={{ color: 'var(--text-tertiary)' }}>
                                    <Bot className="w-4 h-4" /> Service Accounts (Bots)
                                </h3>
                                <button
                                    onClick={handleCreateBot}
                                    className="text-xs px-3 py-1.5 bg-purple-600 hover:bg-purple-500 rounded text-white font-medium transition-colors flex items-center gap-1.5"
                                >
                                    <Plus className="w-3 h-3" /> Create Bot
                                </button>
                            </div>

                            <div className="p-4 rounded-lg border" style={{ backgroundColor: 'var(--bg-panel)', borderColor: 'var(--border-subtle)' }}>
                                <div className="space-y-3">
                                    {bots.length === 0 && (
                                        <div className="text-center py-8 text-xs italic flex flex-col items-center gap-2" style={{ color: 'var(--text-tertiary)' }}>
                                            <Bot className="w-8 h-8 opacity-20" />
                                            No service accounts yet.
                                        </div>
                                    )}
                                    {bots.map(bot => (
                                        <div key={bot.id} className="flex items-center justify-between p-3 rounded border transition-colors hover:bg-white/5" style={{ backgroundColor: 'rgba(0,0,0,0.15)', borderColor: 'var(--border-subtle)' }}>
                                            <div className="flex items-center gap-3">
                                                <div className="w-8 h-8 rounded bg-purple-500/20 text-purple-400 flex items-center justify-center">
                                                    <Bot className="w-5 h-5" />
                                                </div>
                                                <div>
                                                    <div className="font-medium text-sm">{bot.display_name}</div>
                                                    <div className="text-[10px] font-mono" style={{ color: 'var(--text-tertiary)' }}>@{bot.name}</div>
                                                </div>
                                            </div>
                                            <div className="flex items-center gap-1">
                                                <button onClick={() => handleCopyConfig(bot.id)} className="text-[10px] px-2 py-1 rounded bg-white/5 hover:bg-white/10 transition-colors flex items-center gap-1"><Copy className="w-3 h-3" /> Config</button>
                                                <button onClick={() => handleDeleteBot(bot.id, bot.display_name)} className="text-xs text-red-400 hover:text-red-300 p-2 rounded hover:bg-red-500/10 transition-colors"><Trash2 className="w-4 h-4" /></button>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </section>

                        {/* ── Admin: All Profiles ────────────────────────────────────── */}
                        {isAdmin && (
                            <section className="grid gap-3">
                                <h3 className="text-xs font-bold uppercase tracking-wider flex items-center gap-2" style={{ color: 'var(--text-tertiary)' }}>
                                    <Shield className="w-4 h-4" /> All Profiles
                                </h3>
                                <div className="grid gap-2">
                                    {profiles.map(p => (
                                        <div key={p.id} className="flex items-center justify-between rounded-lg px-4 py-3 group border transition-colors hover:border-gray-600" style={{ backgroundColor: 'var(--bg-panel)', borderColor: 'var(--border-subtle)' }}>
                                            <div className="flex items-center gap-3">
                                                <div className="w-10 h-10 rounded-full flex items-center justify-center font-bold text-lg" style={{ backgroundColor: 'var(--accent-subtle)', color: 'var(--accent-primary)' }}>
                                                    {(p.display_name || p.name)[0]?.toUpperCase()}
                                                </div>
                                                <div className="flex flex-col text-sm">
                                                    <span className="font-medium">{p.display_name || p.name}</span>
                                                    <span className="text-[10px]" style={{ color: 'var(--text-tertiary)' }}>@{p.name}</span>
                                                </div>
                                                <span className="text-[10px] px-2 py-0.5 rounded-full font-bold uppercase tracking-tighter ml-2" style={roleBadge(p.role)}>{p.role || 'member'}</span>
                                            </div>
                                            {p.name !== 'admin' && (
                                                <button onClick={() => handleDeleteProfile(p.id, p.display_name || p.name)} className="opacity-0 group-hover:opacity-100 transition-all p-2 rounded hover:bg-red-500/10 text-red-400"><Trash2 className="w-4 h-4" /></button>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            </section>
                        )}
                    </div>
                ) : (
                    <div className="flex flex-col h-full overflow-hidden animate-in fade-in slide-in-from-right-2 duration-300">
                        {/* ── Security Sub-tabs ────────────────────────────────────────── */}
                        <div className="flex items-center justify-between mb-4 border-b flex-shrink-0" style={{ borderColor: 'var(--border-subtle)' }}>
                            <nav className="flex gap-6">
                                <button
                                    onClick={() => { setSecuritySubTab('roles'); setSearchQuery(''); }}
                                    className={`pb-2 text-xs font-bold uppercase tracking-wider border-b-2 transition-all ${securitySubTab === 'roles' ? 'border-purple-500 text-purple-400' : 'border-transparent text-secondary hover:text-primary'}`}
                                >
                                    Roles
                                </button>
                                <button
                                    onClick={() => { setSecuritySubTab('permissions'); setSearchQuery(''); }}
                                    className={`pb-2 text-xs font-bold uppercase tracking-wider border-b-2 transition-all ${securitySubTab === 'permissions' ? 'border-purple-500 text-purple-400' : 'border-transparent text-secondary hover:text-primary'}`}
                                >
                                    Permissions
                                </button>
                            </nav>
                            <div className="flex gap-2 mb-2">
                                {securitySubTab === 'roles' ? (
                                    <button onClick={handleCreateRole} className="text-[10px] px-3 py-1 bg-purple-600 hover:bg-purple-500 rounded text-white font-bold transition-all flex items-center gap-1">
                                        <Plus className="w-3 h-3" /> Create Role
                                    </button>
                                ) : (
                                    <button onClick={handleCreatePermission} className="text-[10px] px-3 py-1 bg-green-600 hover:bg-green-500 rounded text-white font-bold transition-all flex items-center gap-1">
                                        <Plus className="w-3 h-3" /> Create Permission
                                    </button>
                                )}
                            </div>
                        </div>

                        {/* ── Search Bar ──────────────────────────────────────────────── */}
                        <div className="mb-4 relative flex-shrink-0">
                            <input
                                type="text"
                                placeholder={`Search ${securitySubTab}...`}
                                value={searchQuery}
                                onChange={(e) => setSearchQuery(e.target.value)}
                                className="w-full bg-black/20 border rounded-lg px-4 py-2 text-sm focus:outline-none focus:border-purple-500/50 transition-all"
                                style={{ borderColor: 'var(--border-subtle)' }}
                            />
                        </div>

                        {/* ── Content Area ────────────────────────────────────────────── */}
                        <div className="flex-1 overflow-y-auto">
                            {securitySubTab === 'roles' ? (
                                <div className="space-y-4">
                                    {roles.filter(r => r.name.toLowerCase().includes(searchQuery.toLowerCase())).map(role => {
                                        const groups = {
                                            'Project Management': allPermissions.filter(p => p.codename.startsWith('project:')),
                                            'Task Management': allPermissions.filter(p => p.codename.startsWith('task:') || p.codename.startsWith('attachment:')),
                                            'Activity & Comments': allPermissions.filter(p => p.codename.startsWith('activity:')),
                                            'Status Transitions': allPermissions.filter(p => p.codename.startsWith('transition:')),
                                            'System Security': allPermissions.filter(p =>
                                                p.codename.startsWith('role:') ||
                                                p.codename.startsWith('permission:') ||
                                                p.codename.startsWith('profile:')
                                            ),
                                            'Other': allPermissions.filter(p =>
                                                !p.codename.startsWith('project:') &&
                                                !p.codename.startsWith('task:') &&
                                                !p.codename.startsWith('activity:') &&
                                                !p.codename.startsWith('attachment:') &&
                                                !p.codename.startsWith('transition:') &&
                                                !p.codename.startsWith('role:') &&
                                                !p.codename.startsWith('permission:') &&
                                                !p.codename.startsWith('profile:')
                                            )
                                        };

                                        return (
                                            <div key={role.id} className="rounded-xl border overflow-hidden" style={{ backgroundColor: 'var(--bg-panel)', borderColor: 'var(--border-subtle)' }}>
                                                <div
                                                    className="p-4 flex items-center justify-between cursor-pointer hover:bg-white/5 transition-all"
                                                    onClick={() => setSelectedRoleName(selectedRoleName === role.name ? null : role.name)}
                                                >
                                                    <div className="flex items-center gap-3">
                                                        <Shield className={`w-5 h-5 ${selectedRoleName === role.name ? 'text-purple-400' : 'text-secondary'}`} />
                                                        <div>
                                                            <div className="font-bold text-sm uppercase tracking-wide">{role.name}</div>
                                                            <div className="text-[10px] text-tertiary">{role.permissions.length} permissions assigned</div>
                                                        </div>
                                                    </div>
                                                    <ChevronRight className={`w-4 h-4 transition-transform duration-200 ${selectedRoleName === role.name ? 'rotate-90' : 'opacity-40'}`} />
                                                </div>

                                                {selectedRoleName === role.name && (
                                                    <div className="p-4 pt-0 border-t space-y-6 animate-in slide-in-from-top-1 duration-200" style={{ borderColor: 'var(--border-subtle)' }}>
                                                        <div className="mt-4 text-[11px] text-secondary italic mb-4">{role.description || 'No description provided for this role.'}</div>

                                                        <div className="space-y-6">
                                                            {Object.entries(groups).map(([groupName, perms]) => perms.length > 0 && (
                                                                <div key={groupName} className="space-y-3">
                                                                    <h5 className="text-[10px] font-bold uppercase tracking-widest text-secondary px-1 border-l-2 border-purple-500/50">
                                                                        {groupName}
                                                                    </h5>
                                                                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
                                                                        {perms.map(perm => {
                                                                            const isGranted = role.permissions.includes(perm.codename);
                                                                            return (
                                                                                <div
                                                                                    key={perm.id}
                                                                                    className={`p-2.5 rounded-lg border flex items-center justify-between cursor-pointer transition-all ${isGranted ? 'bg-purple-500/10 border-purple-500/30' : 'bg-black/20 border-white/5 opacity-60 hover:opacity-100'}`}
                                                                                    onClick={() => togglePermission(role.name, perm.codename, isGranted)}
                                                                                >
                                                                                    <div className="flex flex-col overflow-hidden">
                                                                                        <span className="text-[10px] font-mono leading-tight truncate">{perm.codename}</span>
                                                                                        <span className="text-[8px] text-tertiary mt-0.5 truncate">{perm.description || 'No description'}</span>
                                                                                    </div>
                                                                                    <div className={`w-3.5 h-3.5 rounded-full flex items-center justify-center border flex-shrink-0 ml-2 ${isGranted ? 'bg-purple-500 border-purple-400' : 'border-white/20'}`}>
                                                                                        {isGranted && <Check className="w-2 h-2 text-white" />}
                                                                                    </div>
                                                                                </div>
                                                                            );
                                                                        })}
                                                                    </div>
                                                                </div>
                                                            ))}
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                        );
                                    })}
                                </div>
                            ) : (
                                <div className="rounded-xl border overflow-hidden" style={{ backgroundColor: 'var(--bg-panel)', borderColor: 'var(--border-subtle)' }}>
                                    <table className="w-full text-left border-collapse">
                                        <thead>
                                            <tr style={{ borderBottom: '1px solid var(--border-subtle)', backgroundColor: 'rgba(0,0,0,0.2)' }}>
                                                <th className="p-3 text-[10px] font-bold uppercase tracking-widest text-tertiary">Permission</th>
                                                <th className="p-3 text-[10px] font-bold uppercase tracking-widest text-tertiary">Assigned Roles</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {allPermissions.filter(p =>
                                                p.codename.toLowerCase().includes(searchQuery.toLowerCase()) ||
                                                p.description?.toLowerCase().includes(searchQuery.toLowerCase())
                                            ).map(perm => {
                                                const assignedRoles = roles.filter(r => r.permissions.includes(perm.codename));
                                                return (
                                                    <tr key={perm.id} className="hover:bg-white/5 transition-colors" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                                                        <td className="p-3">
                                                            <div className="flex flex-col">
                                                                <span className="text-[11px] font-mono font-bold text-primary">{perm.codename}</span>
                                                                <span className="text-[9px] text-tertiary">{perm.description || 'No description'}</span>
                                                            </div>
                                                        </td>
                                                        <td className="p-3">
                                                            <div className="flex flex-wrap gap-1">
                                                                {assignedRoles.length > 0 ? assignedRoles.map(r => (
                                                                    <span key={r.id} className="text-[9px] px-2 py-0.5 rounded font-bold uppercase" style={{ backgroundColor: 'rgba(124,77,255,0.15)', color: 'var(--accent-primary)', border: '1px solid rgba(124,77,255,0.3)' }}>
                                                                        {r.name}
                                                                    </span>
                                                                )) : (
                                                                    <span className="text-[9px] text-tertiary italic">No roles assigned</span>
                                                                )}
                                                            </div>
                                                        </td>
                                                    </tr>
                                                );
                                            })}
                                        </tbody>
                                    </table>
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </div>

            {/* ── API Key Modal ──────────────────────────────────────────── */}
            {newBotKey && (
                <div className="fixed inset-0 flex items-center justify-center z-50 bg-black/60 backdrop-blur-sm">
                    <div className="w-full max-w-lg mx-4 rounded-xl shadow-2xl p-6 space-y-4 border bg-card" style={{ borderColor: 'var(--border-subtle)' }}>
                        <div className="flex items-center gap-3">
                            <div className="w-10 h-10 rounded-full bg-green-500/15 text-green-400 flex items-center justify-center"><Key className="w-5 h-5" /></div>
                            <div>
                                <h3 className="font-bold text-lg">Bot Created!</h3>
                                <p className="text-xs text-secondary">Save this API key — it will not be shown again.</p>
                            </div>
                        </div>
                        <div>
                            <label className="text-xs font-semibold uppercase mb-1 block text-tertiary">API Key</label>
                            <div className="flex items-center gap-2">
                                <input id="api-key-display" readOnly value={newBotKey.api_key} className="flex-1 font-mono text-xs p-3 rounded border bg-black/30 select-all" style={{ borderColor: 'var(--border-subtle)' }} onClick={e => e.target.select()} />
                                <button onClick={handleCopyKey} className="px-3 py-3 rounded bg-white/10 hover:bg-white/15 transition-colors flex items-center gap-1.5 text-xs font-medium">
                                    {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                                </button>
                                <button onClick={() => handleCopyConfig(null, newBotKey.api_key)} className="px-3 py-3 rounded bg-purple-600 hover:bg-purple-500 text-white flex items-center gap-1.5 text-xs font-medium">
                                    <Copy className="w-4 h-4" />
                                </button>
                            </div>
                        </div>
                        <div className="flex justify-end pt-2">
                            <button onClick={() => setNewBotKey(null)} className="px-4 py-2 text-sm rounded bg-white/10 hover:bg-white/15">Done</button>
                        </div>
                    </div>
                </div>
            )}

            {/* ── Custom Prompt Modal ────────────────────────────────────── */}
            {promptState && (
                <div className="fixed inset-0 flex items-center justify-center z-[100] bg-black/60 backdrop-blur-sm">
                    <div className="w-full max-w-md mx-4 rounded-xl shadow-2xl p-6 space-y-4 border bg-card" style={{ borderColor: 'var(--border-subtle)' }}>
                        <div>
                            <h3 className="font-bold text-lg">{promptState.title}</h3>
                            <p className="text-xs text-secondary">{promptState.description}</p>
                        </div>
                        <input
                            autoFocus
                            type="text"
                            value={promptState.value}
                            onChange={(e) => setPromptState({ ...promptState, value: e.target.value })}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter') promptState.onConfirm(promptState.value);
                                if (e.key === 'Escape') promptState.onCancel();
                            }}
                            className="w-full bg-black/20 border rounded-lg px-4 py-2 text-sm focus:outline-none focus:border-purple-500/50 transition-all border-border-subtle"
                        />
                        <div className="flex justify-end gap-3 pt-2">
                            <button onClick={promptState.onCancel} className="px-4 py-2 text-sm rounded bg-white/5 hover:bg-white/10">Cancel</button>
                            <button onClick={() => promptState.onConfirm(promptState.value)} className="px-4 py-2 text-sm rounded bg-purple-600 hover:bg-purple-500 text-white font-medium">Confirm</button>
                        </div>
                    </div>
                </div>
            )}

            {/* ── Custom Confirmation Modal ──────────────────────────────── */}
            {confirmState && (
                <div className="fixed inset-0 flex items-center justify-center z-[100] bg-black/60 backdrop-blur-sm">
                    <div className="w-full max-w-md mx-4 rounded-xl shadow-2xl p-6 space-y-4 border bg-card" style={{ borderColor: 'var(--border-subtle)' }}>
                        <div>
                            <h3 className="font-bold text-lg">{confirmState.title}</h3>
                            <p className="text-xs text-secondary mt-1">{confirmState.description}</p>
                        </div>
                        <div className="flex justify-end gap-3 pt-2">
                            <button onClick={confirmState.onCancel} className="px-4 py-2 text-sm rounded bg-white/5 hover:bg-white/10">Cancel</button>
                            <button onClick={confirmState.onConfirm} className="px-4 py-2 text-sm rounded bg-red-600 hover:bg-red-500 text-white font-medium">Delete</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
