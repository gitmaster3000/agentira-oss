import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { useAuth } from '../context/AuthContext';
import { ROUTES } from '../routes';
import { useNavigate } from 'react-router-dom';
import { Bot, Key, Lock, Trash2, Plus, Shield, Copy, Check, User, ChevronRight, RefreshCw, Cog, X } from 'lucide-react';
import { AppearanceSettings } from '../components/settings/AppearanceSettings';

// ── RBAC helpers ────────────────────────────────────────────────────────────
const ALL_ROLES = ['admin', 'member', 'viewer'];

const roleBadge = (role) => ({
    backgroundColor: role === 'admin' ? 'rgba(239,68,68,0.12)' : role === 'viewer' ? 'rgba(96,165,250,0.12)' : 'rgba(46,204,113,0.12)',
    color: role === 'admin' ? '#ef4444' : role === 'viewer' ? '#60a5fa' : '#2ecc71',
});

// Design's exact member role badge colours
const memberBadgeStyle = (role) => role === 'admin'
    ? { background: 'rgba(201,184,255,.12)', color: 'var(--brand-lavender)' }
    : { background: 'rgba(118,131,144,.14)', color: 'var(--text-muted)' };

const ACCOUNT_META = {
    human:          { label: 'Person',          Icon: User },
    agentira_agent: { label: 'Agentira agent',  Icon: Bot  },
    external_agent: { label: 'Service account', Icon: Key  },
};

// ── Nav helpers ──────────────────────────────────────────────────────────────
function NavSection({ children, label, branded }) {
    return (
        <div style={{ marginBottom: 4 }}>
            <div style={{
                fontSize: 10, fontWeight: 700, letterSpacing: '.1em', color: 'var(--text-muted)',
                padding: branded ? '22px 8px 10px' : '0 8px 10px',
                display: 'flex', alignItems: 'center', gap: 7,
            }}>
                {branded && (
                    <span style={{
                        width: 14, height: 14, borderRadius: 4,
                        background: 'linear-gradient(135deg,var(--brand-lavender),var(--brand-teal))',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        fontSize: 8, fontWeight: 800, color: 'var(--surface-base)', flexShrink: 0,
                    }}>A</span>
                )}
                {label}
            </div>
            {children}
        </div>
    );
}

function NavItem({ active, onClick, children }) {
    return (
        <div
            onClick={onClick}
            style={{
                display: 'block', width: '100%', textAlign: 'left',
                padding: '7px 10px', borderRadius: 9, marginBottom: 2,
                fontSize: 13, cursor: 'pointer',
                color: active ? 'var(--text-primary)' : 'var(--text-muted)',
                background: active ? 'var(--bg-hover,var(--surface-hover))' : 'transparent',
                transition: 'background .12s, color .12s',
            }}
            onMouseEnter={e => { if (!active) e.currentTarget.style.background = 'var(--surface-hover)'; }}
            onMouseLeave={e => { if (!active) e.currentTarget.style.background = 'transparent'; }}
        >
            {children}
        </div>
    );
}

// ── Role chips (editable) ────────────────────────────────────────────────────
function RoleChips({ value, onChange, disabled }) {
    function toggle(r) {
        const next = value.includes(r) ? value.filter(x => x !== r) : [...value, r];
        if (next.length) onChange(next);
    }
    return (
        <div className="flex gap-2 flex-wrap">
            {ALL_ROLES.map(r => {
                const on = value.includes(r);
                return (
                    <button key={r} type="button" disabled={disabled} onClick={() => toggle(r)}
                        className={`text-[11px] px-2.5 py-1 rounded-full font-bold uppercase tracking-tight border transition-all ${on ? '' : 'opacity-40 hover:opacity-70'}`}
                        style={on ? { ...roleBadge(r), borderColor: 'transparent' } : { borderColor: 'var(--border-subtle)', color: 'var(--text-tertiary)' }}>
                        {r}
                    </button>
                );
            })}
        </div>
    );
}

// ── Shared field label ───────────────────────────────────────────────────────
const FL = ({ children }) => (
    <div style={{ fontSize: 11.5, color: 'var(--text-muted)', marginBottom: 6 }}>{children}</div>
);

// ── Read-only display field (matches design's input-style row) ───────────────
const DisplayField = ({ value, mono, style }) => (
    <div style={{
        padding: '10px 13px', borderRadius: 10,
        background: 'var(--surface-card)', border: '1px solid var(--border-default)',
        fontSize: mono ? 12.5 : 13,
        fontFamily: mono ? 'ui-monospace,monospace' : undefined,
        color: mono ? 'var(--text-muted)' : 'var(--text-primary)',
        ...style,
    }}>{value || '— none —'}</div>
);

// ── Editable input that looks like the design's DisplayField ─────────────────
const SettingsInput = ({ type = 'text', value, onChange, placeholder, autoComplete, mono, ...rest }) => (
    <input
        type={type}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        autoComplete={autoComplete}
        style={{
            width: '100%', padding: '10px 13px', borderRadius: 10,
            background: 'var(--surface-card)', border: '1px solid var(--border-default)',
            fontSize: mono ? 12.5 : 13, color: 'var(--text-primary)',
            fontFamily: mono ? 'ui-monospace,monospace' : undefined,
            outline: 'none',
            transition: 'border-color .15s',
        }}
        onFocus={e => { e.target.style.borderColor = 'var(--accent-primary)'; }}
        onBlur={e => { e.target.style.borderColor = 'var(--border-default)'; }}
        {...rest}
    />
);

// ── Row card (Members / Accounts rows) ──────────────────────────────────────
const Row = ({ onClick, children, style }) => (
    <div
        onClick={onClick}
        style={{
            display: 'flex', alignItems: 'center', gap: 11,
            padding: '11px 13px', borderRadius: 10,
            background: 'var(--surface-card)', border: '1px solid var(--border-default)',
            marginBottom: 7, cursor: onClick ? 'pointer' : undefined,
            transition: 'border-color .15s',
            ...style,
        }}
        onMouseEnter={e => { if (onClick) e.currentTarget.style.borderColor = 'var(--accent-primary)'; }}
        onMouseLeave={e => { if (onClick) e.currentTarget.style.borderColor = 'var(--border-default)'; }}
    >
        {children}
    </div>
);

// ── Avatar (human = initial, bot = icon) ────────────────────────────────────
function Avatar({ profile, size = 30, radius = '50%' }) {
    const meta = ACCOUNT_META[profile?.account_type] || ACCOUNT_META.human;
    const isHuman = !profile?.account_type || profile?.account_type === 'human';
    const initial = ((profile?.display_name || profile?.name || '?')[0]).toUpperCase();
    return (
        <span style={{
            width: size, height: size, borderRadius: radius, flexShrink: 0,
            background: 'rgba(201,184,255,.14)', color: 'var(--brand-lavender)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: size === 54 ? 20 : 12.5, fontWeight: 600,
        }}>
            {isHuman ? initial : <meta.Icon style={{ width: size * 0.5, height: size * 0.5 }} />}
        </span>
    );
}

// ── Role badge (display-only) ────────────────────────────────────────────────
function RoleBadge({ role }) {
    if (!role) return null;
    return (
        <span style={{
            padding: '2px 8px', borderRadius: 20,
            fontSize: 10.5, fontWeight: 600,
            ...memberBadgeStyle(role),
        }}>{role}</span>
    );
}

function RoleBadges({ roles }) {
    if (!roles?.length) return null;
    return <>{roles.map(r => <RoleBadge key={r} role={r} />)}</>;
}

// ── Sub-section label (like "BOT KEYS ·" in accounts) ───────────────────────
const SubLabel = ({ children }) => (
    <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.08em', color: 'var(--text-muted)' }}>
        {children}
    </div>
);

// ── Accent button (Invite / New) ─────────────────────────────────────────────
const AccentBtn = ({ onClick, children }) => (
    <button
        onClick={onClick}
        style={{
            display: 'flex', alignItems: 'center', gap: 6,
            padding: '7px 12px', borderRadius: 9,
            background: 'var(--accent-primary,var(--brand-lavender))',
            color: 'var(--accent-on,var(--accent-on))',
            fontSize: 12.5, fontWeight: 600, cursor: 'pointer',
            border: 'none', flexShrink: 0,
        }}
    >{children}</button>
);

// ── Ghost button (Regenerate / secondary actions) ────────────────────────────
const GhostBtn = ({ onClick, children, danger, disabled }) => (
    <button
        onClick={onClick}
        disabled={disabled}
        style={{
            display: 'flex', alignItems: 'center', gap: 6,
            padding: '8px 14px', borderRadius: 9,
            border: '1px solid var(--border-default)',
            background: 'transparent',
            color: danger ? '#f87171' : 'var(--text-tertiary)',
            fontSize: 12.5, cursor: 'pointer',
            transition: 'border-color .15s, color .15s',
        }}
        onMouseEnter={e => {
            e.currentTarget.style.borderColor = danger ? '#f87171' : 'var(--accent-primary)';
            if (!danger) e.currentTarget.style.color = 'var(--text-primary)';
        }}
        onMouseLeave={e => {
            e.currentTarget.style.borderColor = 'var(--border-default)';
            e.currentTarget.style.color = danger ? '#f87171' : 'var(--text-tertiary)';
        }}
    >{children}</button>
);

// ── Modal wrapper ────────────────────────────────────────────────────────────
function Modal({ onClose, maxWidth = 448, children }) {
    return (
        <div
            style={{
                position: 'fixed', inset: 0, zIndex: 100,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                background: 'rgba(0,0,0,.6)', backdropFilter: 'blur(4px)',
            }}
            onClick={onClose}
        >
            <div
                style={{
                    width: '100%', maxWidth, margin: '0 16px',
                    borderRadius: 14, boxShadow: '0 24px 48px rgba(0,0,0,.6)',
                    border: '1px solid var(--border-default)',
                    background: 'var(--bg-card,var(--surface-nav))',
                    padding: 24, display: 'flex', flexDirection: 'column', gap: 16,
                }}
                onClick={e => e.stopPropagation()}
            >
                {children}
            </div>
        </div>
    );
}

// ── InfoBanner (dashed border notice) ───────────────────────────────────────
const InfoBanner = ({ children }) => (
    <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '10px 13px', borderRadius: 10,
        background: 'rgba(118,131,144,.06)', border: '1px dashed var(--border-default)',
        fontSize: 11.5, color: 'var(--text-muted)',
    }}>{children}</div>
);

// ── ProfileDetailsModal ──────────────────────────────────────────────────────
function ProfileDetailsModal({ profile, editable, onClose, onSaved, onDelete, onCopyKey, onCopyConfig, onRegenerateKey, onConfigure }) {
    const meta = ACCOUNT_META[profile.account_type] || ACCOUNT_META.human;
    const isHuman = !profile.account_type || profile.account_type === 'human';
    const isService = profile.account_type === 'external_agent';
    const isAgent = profile.account_type === 'agentira_agent';
    const isSelfAdmin = profile.name === 'admin';

    const [displayName, setDisplayName] = useState(profile.display_name || '');
    const [email, setEmail] = useState(profile.email || '');
    const [roles, setRoles] = useState(profile.roles || (profile.role ? [profile.role] : []));
    const [tempPw, setTempPw] = useState(null);
    const [err, setErr] = useState('');
    const [busy, setBusy] = useState(false);

    const savedRoles = profile.roles || (profile.role ? [profile.role] : []);
    const patch = {};
    if (displayName !== (profile.display_name || '')) patch.display_name = displayName;
    if (isHuman && email !== (profile.email || '')) patch.email = email;
    if (roles.length !== savedRoles.length || roles.some(r => !savedRoles.includes(r))) patch.roles = roles;
    const dirty = Object.keys(patch).length > 0;

    async function save() {
        setErr(''); setBusy(true);
        try { await api.updateProfile(profile.id, patch); await onSaved(); }
        catch (e) { setErr(e.message); setBusy(false); }
    }

    async function resetPassword() {
        setErr(''); setBusy(true);
        try { setTempPw((await api.resetMemberPassword(profile.id)).temp_password); }
        catch (e) { setErr(e.message); }
        finally { setBusy(false); }
    }

    return (
        <div
            style={{ position: 'fixed', inset: 0, zIndex: 90, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,.6)', backdropFilter: 'blur(4px)' }}
            onClick={onClose}
        >
            <div
                style={{ width: '100%', maxWidth: 440, margin: '0 16px', borderRadius: 14, boxShadow: '0 24px 48px rgba(0,0,0,.6)', border: '1px solid var(--border-default)', background: 'var(--bg-card,var(--surface-nav))', overflow: 'hidden' }}
                onClick={e => e.stopPropagation()}
            >
                {/* Header */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '18px 20px', borderBottom: '1px solid var(--border-default)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
                        <Avatar profile={profile} size={38} radius={isHuman ? '50%' : 9} />
                        <div style={{ minWidth: 0 }}>
                            <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{profile.display_name || profile.name}</div>
                            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 1 }}>@{profile.name} · {meta.label}</div>
                        </div>
                    </div>
                    {editable ? (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                            <GhostBtn onClick={onClose}>Cancel</GhostBtn>
                            <button
                                onClick={save} disabled={!dirty || busy}
                                style={{ padding: '7px 16px', borderRadius: 9, background: 'var(--accent-primary,var(--brand-lavender))', color: 'var(--accent-on,var(--accent-on))', fontSize: 12.5, fontWeight: 600, border: 'none', cursor: dirty && !busy ? 'pointer' : 'default', opacity: (!dirty || busy) ? 0.4 : 1 }}
                            >{busy ? 'Saving…' : 'Save'}</button>
                        </div>
                    ) : (
                        <button onClick={onClose} style={{ padding: 6, borderRadius: 8, background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}><X style={{ width: 16, height: 16 }} /></button>
                    )}
                </div>

                <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 18 }}>
                    {err && <div style={{ padding: '8px 12px', borderRadius: 8, fontSize: 12, color: '#f87171', background: 'rgba(248,113,113,.08)', border: '1px solid rgba(248,113,113,.25)' }}>{err}</div>}

                    {/* Display name */}
                    {editable && (
                        <div><FL>Display name</FL><SettingsInput value={displayName} onChange={e => setDisplayName(e.target.value)} placeholder={profile.name} /></div>
                    )}

                    {/* Roles */}
                    <div>
                        <FL>Roles</FL>
                        {editable ? <RoleChips value={roles} onChange={setRoles} disabled={busy} /> : <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}><RoleBadges roles={roles} /></div>}
                    </div>

                    {/* Email — people only */}
                    {isHuman && editable && (
                        <div><FL>Email</FL><SettingsInput type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="user@example.com" /></div>
                    )}

                    {/* Password reset — admin resets someone else's */}
                    {isHuman && editable && (
                        <div style={{ borderTop: '1px solid var(--border-default)', paddingTop: 16 }}>
                            <FL>Password</FL>
                            {tempPw ? (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                    <div style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>Temporary — share securely. User changes it on next sign-in.</div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                        <input readOnly value={tempPw} onClick={e => e.target.select()}
                                            style={{ flex: 1, padding: '10px 13px', borderRadius: 10, background: 'var(--surface-card)', border: '1px solid var(--border-default)', fontSize: 13, fontFamily: 'ui-monospace,monospace', color: 'var(--text-tertiary)', outline: 'none' }} />
                                        <button onClick={() => navigator.clipboard?.writeText(tempPw)}
                                            style={{ padding: '10px 12px', borderRadius: 9, border: '1px solid var(--border-default)', background: 'transparent', color: 'var(--text-tertiary)', cursor: 'pointer' }}>
                                            <Copy style={{ width: 14, height: 14 }} />
                                        </button>
                                    </div>
                                </div>
                            ) : (
                                <GhostBtn onClick={resetPassword} disabled={busy}>Reset password</GhostBtn>
                            )}
                        </div>
                    )}

                    {/* API key actions — service accounts only */}
                    {isService && (
                        <div style={{ borderTop: '1px solid var(--border-default)', paddingTop: 16 }}>
                            <FL>API key</FL>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                                <GhostBtn onClick={onCopyKey}><Key style={{ width: 13, height: 13 }} /> Copy key</GhostBtn>
                                <GhostBtn onClick={onCopyConfig}><Copy style={{ width: 13, height: 13 }} /> Copy MCP config</GhostBtn>
                                {editable && <GhostBtn onClick={onRegenerateKey}><RefreshCw style={{ width: 13, height: 13 }} /> Regenerate</GhostBtn>}
                            </div>
                        </div>
                    )}

                    {/* Configure — managed agents only */}
                    {isAgent && (
                        <div style={{ borderTop: '1px solid var(--border-default)', paddingTop: 16 }}>
                            <FL>Configuration</FL>
                            <GhostBtn onClick={onConfigure}><Cog style={{ width: 13, height: 13 }} /> Open agent settings</GhostBtn>
                        </div>
                    )}

                    {/* Delete */}
                    {editable && !isSelfAdmin && (
                        <div style={{ borderTop: '1px solid var(--border-default)', paddingTop: 14 }}>
                            <GhostBtn onClick={onDelete} danger>
                                <Trash2 style={{ width: 13, height: 13 }} />
                                Delete {meta.label.toLowerCase()}
                            </GhostBtn>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

// ════════════════════════════════════════════════════════════════════════════
// Main Settings component
// ════════════════════════════════════════════════════════════════════════════
export function Settings() {
    const { user } = useAuth();
    const navigate = useNavigate();
    const [activeTab, setActiveTab] = useState('profile');

    // Data
    const [me, setMe] = useState(null);
    const [profiles, setProfiles] = useState([]);
    const [bots, setBots] = useState([]);
    const [roles, setRoles] = useState([]);
    const [allPermissions, setAllPermissions] = useState([]);
    const [loading, setLoading] = useState(true);

    // Profile tab local state
    const [displayName, setDisplayName] = useState('');
    const [profileEmail, setProfileEmail] = useState('');
    const [profileSaving, setProfileSaving] = useState(false);
    const [profileMsg, setProfileMsg] = useState('');

    // Security tab local state
    const [pw, setPw] = useState({ next: '', confirm: '' });
    const [pwSaving, setPwSaving] = useState(false);
    const [pwMsg, setPwMsg] = useState('');

    // RBAC
    const [secSubTab, setSecSubTab] = useState('roles');
    const [searchQuery, setSearchQuery] = useState('');
    const [selectedRoleName, setSelectedRoleName] = useState(null);

    // Modals
    const [newBotKey, setNewBotKey] = useState(null);
    const [copied, setCopied] = useState(false);
    const [promptState, setPromptState] = useState(null);
    const [confirmState, setConfirmState] = useState(null);
    const [managing, setManaging] = useState(null);

    const isAdmin = user?.roles?.includes?.('admin') || user?.role === 'admin' || user?.role?.name === 'admin';
    const isHumanUser = !me?.account_type || me?.account_type === 'human';

    useEffect(() => {
        if (!user) { navigate(ROUTES.LOGIN); return; }
        loadGeneral();
    }, [user, navigate]);

    useEffect(() => {
        if (activeTab === 'permissions' && isAdmin) loadPermissions();
    }, [activeTab, isAdmin]);

    async function loadGeneral() {
        setLoading(true);
        try {
            const meData = await api.getMe();
            setMe(meData);
            setDisplayName(meData.display_name || '');
            setProfileEmail(meData.email || '');
        } catch (err) { console.error(err); }
        try { setBots(await api.listServiceAccounts()); } catch { /* ignore */ }
        if (isAdmin) {
            try { setProfiles(await api.getProfiles()); } catch { /* ignore */ }
        }
        setLoading(false);
    }

    async function loadPermissions() {
        setLoading(true);
        try {
            const [r, p] = await Promise.all([api.getRoles(), api.getPermissions()]);
            setRoles(r); setAllPermissions(p);
        } catch (err) { console.error(err); }
        finally { setLoading(false); }
    }

    // ── Profile tab actions ────────────────────────────────────────────────
    const profileDirty = me && (
        displayName !== (me.display_name || '') || profileEmail !== (me.email || '')
    );

    async function saveProfile() {
        const patch = {};
        if (displayName !== (me.display_name || '')) patch.display_name = displayName;
        if (isHumanUser && profileEmail !== (me.email || '')) patch.email = profileEmail;
        if (!Object.keys(patch).length) return;
        setProfileSaving(true); setProfileMsg('');
        try {
            await api.updateProfile(me.id, patch);
            setMe({ ...me, ...patch });
            setProfileMsg('saved');
        } catch (e) { setProfileMsg(e.message || 'Failed to save'); }
        finally { setProfileSaving(false); }
    }

    // ── Security tab actions ───────────────────────────────────────────────
    async function changePassword() {
        setPwMsg('');
        if (pw.next.length < 8) { setPwMsg('Use at least 8 characters.'); return; }
        if (pw.next !== pw.confirm) { setPwMsg('Passwords do not match.'); return; }
        setPwSaving(true);
        try {
            await api.changeMyPassword(pw.next);
            setPw({ next: '', confirm: '' });
            setPwMsg('saved');
        } catch (e) { setPwMsg(e.message || 'Could not update password'); }
        finally { setPwSaving(false); }
    }

    // ── Members / Accounts actions ─────────────────────────────────────────
    async function handleInviteMember() {
        try {
            const inv = await api.createInvite();
            const link = `${window.location.origin}/signup?invite=${inv.code}`;
            try { await navigator.clipboard.writeText(link); } catch { /* ignore */ }
            window.prompt("Invite link (copied to clipboard) — share it:", link);
        } catch (err) { alert(err.message || "Failed to create invite"); }
    }

    function handleCreateBot() {
        setPromptState({
            title: "New bot key",
            description: "Name this bot key (API-key identity for external MCP clients like Cursor or Claude Desktop):",
            value: "",
            onConfirm: async (name) => {
                if (!name) return;
                try {
                    const res = await api.createServiceAccount(name);
                    setNewBotKey({ name: res.name || name, api_key: res.api_key, title: "Bot key created" });
                    setCopied(false);
                    await loadGeneral();
                } catch (err) { alert(err.message); }
                finally { setPromptState(null); }
            },
            onCancel: () => setPromptState(null),
        });
    }

    async function copyKey(botId) {
        try {
            const data = await api.getServiceAccount(botId);
            if (!data?.api_key) { alert("No API key found."); return; }
            await navigator.clipboard.writeText(data.api_key);
            alert("API key copied to clipboard.");
        } catch (err) { alert("Failed to copy key: " + err.message); }
    }

    async function copyConfig(botId, botKey = null) {
        try {
            let key = botKey;
            if (!key) key = (await api.getServiceAccount(botId)).api_key;
            const mcpUrl = `${window.location.protocol}//${window.location.hostname}:8000/sse`;
            const config = { agentira: { url: mcpUrl, headers: { Authorization: `Bearer ${key}` } } };
            await navigator.clipboard.writeText(JSON.stringify(config, null, 2));
            alert("MCP configuration copied to clipboard.");
        } catch (err) { alert("Failed to copy config: " + err.message); }
    }

    async function handleCopyKey() {
        if (!newBotKey) return;
        try {
            await navigator.clipboard.writeText(newBotKey.api_key);
            setCopied(true); setTimeout(() => setCopied(false), 2000);
        } catch {
            const el = document.getElementById('api-key-display');
            if (el) { el.select(); document.execCommand('copy'); setCopied(true); setTimeout(() => setCopied(false), 2000); }
        }
    }

    function handleRegenerateKey(bot) {
        setConfirmState({
            title: "Regenerate API key",
            description: `Regenerate the key for "${bot.display_name || bot.name}"? The old key stops working immediately.`,
            confirmLabel: "Regenerate",
            onConfirm: async () => {
                try {
                    const res = await api.regenerateApiKey(bot.id);
                    setNewBotKey({ name: bot.display_name, api_key: res.api_key, title: "New API key" });
                    setCopied(false);
                } catch (err) { alert(err.message); }
                finally { setConfirmState(null); }
            },
            onCancel: () => setConfirmState(null),
        });
    }

    function handleDeleteAccount(p) {
        const isSvc = p.account_type === 'external_agent';
        setConfirmState({
            title: isSvc ? "Delete bot key" : "Delete profile",
            description: `Delete "${p.display_name || p.name}"? This can't be undone.`,
            onConfirm: async () => {
                try {
                    await (isSvc ? api.deleteServiceAccount(p.id) : api.deleteProfile(p.id));
                    setManaging(null);
                    await loadGeneral();
                } catch (err) { alert(err.message); }
                finally { setConfirmState(null); }
            },
            onCancel: () => setConfirmState(null),
        });
    }

    // ── RBAC actions ───────────────────────────────────────────────────────
    async function togglePermission(roleName, codename, isGranted) {
        try {
            if (isGranted) await api.revokePermission(roleName, codename);
            else await api.grantPermission(roleName, codename);
            await loadPermissions();
        } catch (err) { alert(err.message); }
    }

    function handleCreatePermission() {
        setPromptState({
            title: "Create permission",
            description: "Permission codename (e.g. 'project:manage'):",
            value: "",
            onConfirm: async (codename) => {
                if (!codename) return;
                setPromptState({
                    title: "Permission description",
                    description: `Describe '${codename}':`,
                    value: "",
                    onConfirm: async (description) => {
                        try { await api.createPermission({ codename, description }); await loadPermissions(); }
                        catch (err) { alert(err.message); }
                        finally { setPromptState(null); }
                    },
                    onCancel: () => setPromptState(null),
                });
            },
            onCancel: () => setPromptState(null),
        });
    }

    function handleCreateRole() {
        setPromptState({
            title: "Create role",
            description: "Role name (e.g. 'auditor'):",
            value: "",
            onConfirm: async (name) => {
                if (!name) return;
                setPromptState({
                    title: "Role description",
                    description: `Describe role '${name}':`,
                    value: "",
                    onConfirm: async (description) => {
                        try { await api.createRole({ name, description }); await loadPermissions(); }
                        catch (err) { alert(err.message); }
                        finally { setPromptState(null); }
                    },
                    onCancel: () => setPromptState(null),
                });
            },
            onCancel: () => setPromptState(null),
        });
    }

    // ── Derived lists ──────────────────────────────────────────────────────
    const people = profiles.filter(p => (p.account_type || 'human') === 'human');
    const agentiraAgents = profiles.filter(p => p.account_type === 'agentira_agent');
    const botKeys = bots.filter(b => !b.runtime_id);

    // ── Render ─────────────────────────────────────────────────────────────
    if (loading && !me && !roles.length) {
        return <div style={{ padding: 32, textAlign: 'center', fontSize: 13, color: 'var(--text-muted)' }}>Loading…</div>;
    }

    return (
        <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>

            {/* ── Sidebar ─────────────────────────────────────────────────── */}
            <aside style={{ width: 200, flexShrink: 0, borderRight: '1px solid var(--border-default)', background: 'var(--bg-card,var(--surface-nav))', padding: '20px 12px', overflowY: 'auto' }}>
                <NavSection label="ACCOUNT">
                    <NavItem active={activeTab === 'profile'} onClick={() => setActiveTab('profile')}>My profile</NavItem>
                    <NavItem active={activeTab === 'security'} onClick={() => setActiveTab('security')}>Security</NavItem>
                    <NavItem active={activeTab === 'appearance'} onClick={() => setActiveTab('appearance')}>Appearance</NavItem>
                </NavSection>

                {isAdmin && (
                    <NavSection label="ORGANIZATION" branded>
                        <NavItem active={activeTab === 'members'} onClick={() => setActiveTab('members')}>Members</NavItem>
                        <NavItem active={activeTab === 'accounts'} onClick={() => setActiveTab('accounts')}>Accounts</NavItem>
                        <NavItem active={activeTab === 'permissions'} onClick={() => setActiveTab('permissions')}>Permissions</NavItem>
                    </NavSection>
                )}
            </aside>

            {/* ── Content ─────────────────────────────────────────────────── */}
            <div style={{ flex: 1, overflowY: 'auto', padding: '24px 28px' }}>

                {/* ── My profile ─────────────────────────────────────────── */}
                {activeTab === 'profile' && me && (
                    <div style={{ maxWidth: 560 }}>
                        <h2 style={{ fontSize: 17, fontWeight: 600, margin: '0 0 18px', color: 'var(--text-primary)' }}>My profile</h2>

                        {/* Avatar row */}
                        <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 22 }}>
                            <span style={{ width: 54, height: 54, borderRadius: '50%', background: 'rgba(201,184,255,.14)', color: 'var(--brand-lavender)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 20, fontWeight: 600, flexShrink: 0 }}>
                                {(me.display_name || me.name || '?')[0].toUpperCase()}
                            </span>
                        </div>

                        {/* Display name */}
                        <div style={{ marginBottom: 14 }}>
                            <FL>Display name</FL>
                            <SettingsInput value={displayName} onChange={e => setDisplayName(e.target.value)} placeholder={me.name} />
                        </div>

                        {/* Email */}
                        {isHumanUser && (
                            <div style={{ marginBottom: 14 }}>
                                <FL>Email</FL>
                                <SettingsInput type="email" value={profileEmail} onChange={e => setProfileEmail(e.target.value)} placeholder="you@example.com" autoComplete="email" />
                            </div>
                        )}

                        {/* Feedback */}
                        {profileMsg && (
                            <div style={{
                                marginBottom: 12, padding: '7px 12px', borderRadius: 9, fontSize: 12,
                                ...(profileMsg === 'saved'
                                    ? { color: '#4ade80', background: 'rgba(74,222,128,.08)', border: '1px solid rgba(74,222,128,.25)' }
                                    : { color: '#f87171', background: 'rgba(248,113,113,.08)', border: '1px solid rgba(248,113,113,.25)' }),
                            }}>
                                {profileMsg === 'saved' ? 'Changes saved.' : profileMsg}
                            </div>
                        )}

                        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                            <button
                                onClick={saveProfile}
                                disabled={!profileDirty || profileSaving}
                                style={{
                                    padding: '8px 18px', borderRadius: 9, border: 'none',
                                    background: 'var(--accent-primary,var(--brand-lavender))', color: 'var(--accent-on,var(--accent-on))',
                                    fontSize: 13, fontWeight: 600, cursor: (!profileDirty || profileSaving) ? 'default' : 'pointer',
                                    opacity: (!profileDirty || profileSaving) ? 0.4 : 1,
                                }}
                            >{profileSaving ? 'Saving…' : 'Save changes'}</button>
                        </div>
                    </div>
                )}

                {/* ── Security ───────────────────────────────────────────── */}
                {activeTab === 'security' && (
                    <div style={{ maxWidth: 560 }}>
                        <h2 style={{ fontSize: 17, fontWeight: 600, margin: '0 0 6px', color: 'var(--text-primary)' }}>Security</h2>
                        <p style={{ fontSize: 12.5, color: 'var(--text-muted)', margin: '0 0 24px' }}>Your personal credentials for this workspace.</p>

                        {isHumanUser && (
                            <>
                                <SubLabel>CHANGE PASSWORD</SubLabel>
                                <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 12 }}>
                                    <div>
                                        <FL>New password</FL>
                                        <SettingsInput type="password" value={pw.next} onChange={e => setPw(p => ({ ...p, next: e.target.value }))} placeholder="At least 8 characters" autoComplete="new-password" />
                                    </div>
                                    <div>
                                        <FL>Confirm new password</FL>
                                        <SettingsInput type="password" value={pw.confirm} onChange={e => setPw(p => ({ ...p, confirm: e.target.value }))} placeholder="Repeat new password" autoComplete="new-password" />
                                    </div>

                                    {pwMsg && (
                                        <div style={{
                                            padding: '7px 12px', borderRadius: 9, fontSize: 12,
                                            ...(pwMsg === 'saved'
                                                ? { color: '#4ade80', background: 'rgba(74,222,128,.08)', border: '1px solid rgba(74,222,128,.25)' }
                                                : { color: '#f87171', background: 'rgba(248,113,113,.08)', border: '1px solid rgba(248,113,113,.25)' }),
                                        }}>
                                            {pwMsg === 'saved' ? 'Password updated.' : pwMsg}
                                        </div>
                                    )}

                                    <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                                        <button
                                            onClick={changePassword}
                                            disabled={pwSaving || !pw.next}
                                            style={{
                                                padding: '8px 18px', borderRadius: 9, border: 'none',
                                                background: 'var(--accent-primary,var(--brand-lavender))', color: 'var(--accent-on,var(--accent-on))',
                                                fontSize: 13, fontWeight: 600,
                                                cursor: (pwSaving || !pw.next) ? 'default' : 'pointer',
                                                opacity: (pwSaving || !pw.next) ? 0.4 : 1,
                                            }}
                                        >{pwSaving ? 'Updating…' : 'Update password'}</button>
                                    </div>
                                </div>
                            </>
                        )}
                    </div>
                )}

                {/* ── Appearance ─────────────────────────────────────────── */}
                {activeTab === 'appearance' && <AppearanceSettings />}

                {/* ── Members (admin) ────────────────────────────────────── */}
                {activeTab === 'members' && isAdmin && (
                    <div style={{ maxWidth: 580 }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                            <h2 style={{ fontSize: 17, fontWeight: 600, margin: 0, color: 'var(--text-primary)' }}>Members</h2>
                            <AccentBtn onClick={handleInviteMember}>
                                <Plus style={{ width: 13, height: 13 }} /> Invite
                            </AccentBtn>
                        </div>
                        <p style={{ fontSize: 12.5, color: 'var(--text-muted)', margin: '0 0 18px' }}>
                            People with a seat in this workspace. Roles control what they can change org-wide.
                        </p>

                        {people.length === 0 ? (
                            <div style={{ padding: '32px 0', textAlign: 'center', fontSize: 12.5, color: 'var(--text-muted)', fontStyle: 'italic' }}>No members yet.</div>
                        ) : people.map(p => {
                            const primaryRole = (p.roles || [])[0] || p.role;
                            const isMe = me && p.id === me.id;
                            return (
                                <Row key={p.id} onClick={() => setManaging(p)}>
                                    <Avatar profile={p} size={30} />
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                        <div style={{ fontSize: 12.5, color: 'var(--text-primary)' }}>
                                            {p.display_name || p.name}
                                            {isMe && <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}> · you</span>}
                                        </div>
                                        {p.email && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 1 }}>{p.email}</div>}
                                    </div>
                                    {primaryRole && <RoleBadge role={primaryRole} />}
                                </Row>
                            );
                        })}
                    </div>
                )}

                {/* ── Accounts (admin) ───────────────────────────────────── */}
                {activeTab === 'accounts' && isAdmin && (
                    <div style={{ maxWidth: 580 }}>
                        <h2 style={{ fontSize: 17, fontWeight: 600, margin: '0 0 4px', color: 'var(--text-primary)' }}>Accounts</h2>
                        <p style={{ fontSize: 12.5, color: 'var(--text-muted)', margin: '0 0 24px' }}>
                            Non-human identities that can act in this organization — bot keys for external clients and agents run by your daemons.
                        </p>

                        {/* Bot keys */}
                        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 10 }}>
                            <div>
                                <SubLabel>BOT KEYS</SubLabel>
                                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>API-key-only identities (no runtime) for external MCP clients like Cursor or Claude Desktop.</div>
                            </div>
                            <AccentBtn onClick={handleCreateBot}>
                                <Plus style={{ width: 12, height: 12 }} /> New
                            </AccentBtn>
                        </div>

                        {botKeys.length === 0 ? (
                            <div style={{ padding: '20px 13px', borderRadius: 10, background: 'var(--surface-card)', border: '1px solid var(--border-default)', marginBottom: 24, fontSize: 12.5, color: 'var(--text-muted)', fontStyle: 'italic' }}>
                                No bot keys yet.
                            </div>
                        ) : botKeys.map(b => (
                            <Row key={b.id} onClick={() => setManaging(b)} style={{ marginBottom: 8 }}>
                                <span style={{ width: 30, height: 30, borderRadius: 8, background: 'rgba(118,131,144,.14)', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                                    <Key style={{ width: 15, height: 15 }} />
                                </span>
                                <div style={{ flex: 1, minWidth: 0 }}>
                                    <div style={{ fontSize: 12.5, color: 'var(--text-primary)' }}>{b.display_name || b.name}</div>
                                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 1 }}>bot key</div>
                                </div>
                                <span style={{ fontFamily: 'ui-monospace,monospace', fontSize: 11, color: 'var(--text-muted)' }}>agr_sa_••••</span>
                            </Row>
                        ))}

                        {/* Agents section */}
                        <div style={{ marginBottom: 10, marginTop: botKeys.length > 0 ? 18 : 0 }}>
                            <SubLabel>AGENTS</SubLabel>
                            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>Autonomous agents running on Agentira, executed by your own daemons' runtimes. Open any to manage its runtime, toolset &amp; triggers.</div>
                        </div>

                        {agentiraAgents.length === 0 ? (
                            <div style={{ marginBottom: 12, padding: '10px 13px', borderRadius: 10, background: 'rgba(118,131,144,.04)', border: '1px solid var(--border-default)', fontSize: 12.5, color: 'var(--text-muted)', fontStyle: 'italic' }}>
                                No agents yet.
                            </div>
                        ) : agentiraAgents.map(a => (
                            <Row key={a.id} onClick={() => setManaging(a)} style={{ marginBottom: 8 }}>
                                <span style={{ width: 30, height: 30, borderRadius: 8, background: 'rgba(201,184,255,.14)', color: 'var(--brand-lavender)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12.5, fontWeight: 700, flexShrink: 0 }}>
                                    {(a.display_name || a.name || '?')[0].toUpperCase()}
                                </span>
                                <div style={{ flex: 1, minWidth: 0 }}>
                                    <div style={{ fontSize: 12.5, color: 'var(--text-primary)' }}>{a.display_name || a.name}</div>
                                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 1 }}>agent</div>
                                </div>
                                <ChevronRight style={{ width: 15, height: 15, color: 'var(--text-muted)', flexShrink: 0 }} />
                            </Row>
                        ))}

                        <InfoBanner>
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" style={{ stroke: 'var(--text-muted)' }} strokeWidth="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
                            Each agent's runtime, toolset &amp; triggers live in <b style={{ color: 'var(--text-tertiary)', marginLeft: 3 }}>Build → Agents → Settings</b>.
                        </InfoBanner>
                    </div>
                )}

                {/* ── Permissions / RBAC (admin) ─────────────────────────── */}
                {activeTab === 'permissions' && isAdmin && (
                    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
                        {/* Sub-tab bar */}
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, paddingBottom: 12, borderBottom: '1px solid var(--border-default)', flexShrink: 0 }}>
                            <nav style={{ display: 'flex', gap: 24 }}>
                                {['roles', 'permissions'].map(t => (
                                    <button
                                        key={t}
                                        onClick={() => { setSecSubTab(t); setSearchQuery(''); }}
                                        style={{
                                            paddingBottom: 8, fontSize: 12, fontWeight: 700,
                                            textTransform: 'uppercase', letterSpacing: '.08em',
                                            color: secSubTab === t ? 'var(--accent-primary,var(--brand-lavender))' : 'var(--text-muted)',
                                            background: 'none', border: 'none',
                                            borderBottom: `2px solid ${secSubTab === t ? 'var(--accent-primary,var(--brand-lavender))' : 'transparent'}`,
                                            cursor: 'pointer', transition: 'color .15s, border-color .15s',
                                        }}
                                    >{t}</button>
                                ))}
                            </nav>
                            <GhostBtn onClick={secSubTab === 'roles' ? handleCreateRole : handleCreatePermission}>
                                <Plus style={{ width: 13, height: 13 }} />
                                {secSubTab === 'roles' ? 'Create role' : 'Create permission'}
                            </GhostBtn>
                        </div>

                        {/* Search */}
                        <div style={{ marginBottom: 16, flexShrink: 0 }}>
                            <SettingsInput
                                value={searchQuery}
                                onChange={e => setSearchQuery(e.target.value)}
                                placeholder={`Search ${secSubTab}…`}
                            />
                        </div>

                        <div style={{ flex: 1, overflowY: 'auto' }}>
                            {secSubTab === 'roles' ? (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                                    {roles.filter(r => r.name.toLowerCase().includes(searchQuery.toLowerCase())).map(role => {
                                        const groups = {
                                            'Project Management': allPermissions.filter(p => p.codename.startsWith('project:')),
                                            'Task Management': allPermissions.filter(p => p.codename.startsWith('task:') || p.codename.startsWith('attachment:')),
                                            'Activity & Comments': allPermissions.filter(p => p.codename.startsWith('activity:')),
                                            'Status Transitions': allPermissions.filter(p => p.codename.startsWith('transition:')),
                                            'System Security': allPermissions.filter(p => p.codename.startsWith('role:') || p.codename.startsWith('permission:') || p.codename.startsWith('profile:')),
                                            'Other': allPermissions.filter(p => !['project:', 'task:', 'attachment:', 'activity:', 'transition:', 'role:', 'permission:', 'profile:'].some(pfx => p.codename.startsWith(pfx))),
                                        };
                                        const open = selectedRoleName === role.name;
                                        return (
                                            <div key={role.id} style={{ borderRadius: 12, border: '1px solid var(--border-default)', background: 'var(--surface-card)', overflow: 'hidden' }}>
                                                <div
                                                    style={{ padding: '14px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer', transition: 'background .12s' }}
                                                    onClick={() => setSelectedRoleName(open ? null : role.name)}
                                                    onMouseEnter={e => { e.currentTarget.style.background = 'var(--surface-hover)'; }}
                                                    onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
                                                >
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                                                        <Shield style={{ width: 18, height: 18, color: open ? 'var(--brand-lavender)' : 'var(--text-muted)', flexShrink: 0 }} />
                                                        <div>
                                                            <div style={{ fontWeight: 700, fontSize: 13, textTransform: 'uppercase', letterSpacing: '.04em', color: 'var(--text-primary)' }}>{role.name}</div>
                                                            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 1 }}>{role.permissions.length} permissions assigned</div>
                                                        </div>
                                                    </div>
                                                    <ChevronRight style={{ width: 15, height: 15, color: 'var(--text-muted)', transform: open ? 'rotate(90deg)' : 'none', transition: 'transform .2s' }} />
                                                </div>

                                                {open && (
                                                    <div style={{ padding: '0 16px 16px', borderTop: '1px solid var(--border-default)' }}>
                                                        <div style={{ fontSize: 11, color: 'var(--text-muted)', fontStyle: 'italic', margin: '14px 0' }}>{role.description || 'No description.'}</div>
                                                        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                                                            {Object.entries(groups).map(([groupName, perms]) => perms.length > 0 && (
                                                                <div key={groupName}>
                                                                    <div style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.1em', color: 'var(--text-muted)', paddingLeft: 4, borderLeft: '2px solid var(--brand-lavender)', marginBottom: 10 }}>{groupName}</div>
                                                                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(180px,1fr))', gap: 8 }}>
                                                                        {perms.map(perm => {
                                                                            const isGranted = role.permissions.includes(perm.codename);
                                                                            return (
                                                                                <div
                                                                                    key={perm.id}
                                                                                    onClick={() => togglePermission(role.name, perm.codename, isGranted)}
                                                                                    style={{
                                                                                        padding: '9px 10px', borderRadius: 9, cursor: 'pointer',
                                                                                        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                                                                        border: `1px solid ${isGranted ? 'var(--accent-primary,var(--brand-lavender))' : 'var(--border-default)'}`,
                                                                                        background: isGranted ? 'rgba(201,184,255,.08)' : 'rgba(0,0,0,.15)',
                                                                                        opacity: isGranted ? 1 : 0.65,
                                                                                        transition: 'opacity .15s, border-color .15s, background .15s',
                                                                                    }}
                                                                                    onMouseEnter={e => { if (!isGranted) e.currentTarget.style.opacity = 1; }}
                                                                                    onMouseLeave={e => { if (!isGranted) e.currentTarget.style.opacity = 0.65; }}
                                                                                >
                                                                                    <div style={{ overflow: 'hidden' }}>
                                                                                        <div style={{ fontSize: 10, fontFamily: 'ui-monospace,monospace', color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{perm.codename}</div>
                                                                                        <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{perm.description || 'No description'}</div>
                                                                                    </div>
                                                                                    <div style={{ width: 14, height: 14, borderRadius: '50%', border: `1px solid ${isGranted ? 'var(--brand-lavender)' : 'var(--border-default)'}`, background: isGranted ? 'var(--brand-lavender)' : 'transparent', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, marginLeft: 8 }}>
                                                                                        {isGranted && <Check style={{ width: 8, height: 8, color: 'var(--accent-on)' }} />}
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
                                <div style={{ borderRadius: 12, border: '1px solid var(--border-default)', background: 'var(--surface-card)', overflow: 'hidden' }}>
                                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                                        <thead>
                                            <tr style={{ borderBottom: '1px solid var(--border-default)', background: 'var(--surface-nav)' }}>
                                                <th style={{ padding: '10px 14px', textAlign: 'left', fontSize: 10, fontWeight: 700, letterSpacing: '.08em', color: 'var(--text-muted)' }}>Permission</th>
                                                <th style={{ padding: '10px 14px', textAlign: 'left', fontSize: 10, fontWeight: 700, letterSpacing: '.08em', color: 'var(--text-muted)' }}>Assigned roles</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {allPermissions
                                                .filter(p => p.codename.toLowerCase().includes(searchQuery.toLowerCase()) || p.description?.toLowerCase().includes(searchQuery.toLowerCase()))
                                                .map(perm => {
                                                    const assignedRoles = roles.filter(r => r.permissions.includes(perm.codename));
                                                    return (
                                                        <tr key={perm.id} style={{ borderBottom: '1px solid var(--border-default)', transition: 'background .12s' }}
                                                            onMouseEnter={e => { e.currentTarget.style.background = 'var(--surface-hover)'; }}
                                                            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
                                                        >
                                                            <td style={{ padding: '10px 14px' }}>
                                                                <div style={{ fontSize: 11, fontFamily: 'ui-monospace,monospace', fontWeight: 700, color: 'var(--text-primary)' }}>{perm.codename}</div>
                                                                <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 2 }}>{perm.description || 'No description'}</div>
                                                            </td>
                                                            <td style={{ padding: '10px 14px' }}>
                                                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                                                                    {assignedRoles.length > 0
                                                                        ? assignedRoles.map(r => (
                                                                            <span key={r.id} style={{ fontSize: 10, padding: '2px 8px', borderRadius: 5, fontWeight: 700, textTransform: 'uppercase', background: 'rgba(201,184,255,.1)', color: 'var(--brand-lavender)', border: '1px solid rgba(201,184,255,.2)' }}>{r.name}</span>
                                                                        ))
                                                                        : <span style={{ fontSize: 10, color: 'var(--text-muted)', fontStyle: 'italic' }}>No roles assigned</span>
                                                                    }
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

            {/* ── New / regenerated key modal ──────────────────────────────── */}
            {newBotKey && (
                <Modal onClose={() => setNewBotKey(null)} maxWidth={480}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                        <div style={{ width: 40, height: 40, borderRadius: '50%', background: 'rgba(74,222,128,.12)', color: '#4ade80', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                            <Key style={{ width: 18, height: 18 }} />
                        </div>
                        <div>
                            <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>{newBotKey.title || 'Bot key created'}</div>
                            <div style={{ fontSize: 11.5, color: 'var(--text-muted)', marginTop: 2 }}>Save this API key — it won't be shown again.</div>
                        </div>
                    </div>
                    <div>
                        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.06em', color: 'var(--text-muted)', marginBottom: 8, textTransform: 'uppercase' }}>API key</div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <input id="api-key-display" readOnly value={newBotKey.api_key}
                                onClick={e => e.target.select()}
                                style={{ flex: 1, padding: '10px 13px', borderRadius: 10, background: 'var(--surface-card)', border: '1px solid var(--border-default)', fontSize: 12, fontFamily: 'ui-monospace,monospace', color: 'var(--text-tertiary)', outline: 'none' }} />
                            <button onClick={handleCopyKey} style={{ padding: '10px 12px', borderRadius: 9, border: '1px solid var(--border-default)', background: 'transparent', color: 'var(--text-tertiary)', cursor: 'pointer' }}>
                                {copied ? <Check style={{ width: 15, height: 15 }} /> : <Copy style={{ width: 15, height: 15 }} />}
                            </button>
                            <button onClick={() => copyConfig(null, newBotKey.api_key)} style={{ padding: '10px 13px', borderRadius: 9, background: 'var(--brand-lavender)', color: 'var(--accent-on)', border: 'none', cursor: 'pointer', fontSize: 12, fontWeight: 600 }}>
                                Copy MCP
                            </button>
                        </div>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                        <GhostBtn onClick={() => setNewBotKey(null)}>Done</GhostBtn>
                    </div>
                </Modal>
            )}

            {/* ── Prompt modal ─────────────────────────────────────────────── */}
            {promptState && (
                <Modal onClose={promptState.onCancel}>
                    <div>
                        <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>{promptState.title}</div>
                        <div style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>{promptState.description}</div>
                    </div>
                    <SettingsInput
                        autoFocus
                        value={promptState.value}
                        onChange={e => setPromptState({ ...promptState, value: e.target.value })}
                        onKeyDown={e => { if (e.key === 'Enter') promptState.onConfirm(promptState.value); if (e.key === 'Escape') promptState.onCancel(); }}
                    />
                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                        <GhostBtn onClick={promptState.onCancel}>Cancel</GhostBtn>
                        <button onClick={() => promptState.onConfirm(promptState.value)} style={{ padding: '8px 18px', borderRadius: 9, background: 'var(--brand-lavender)', color: 'var(--accent-on)', border: 'none', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>Confirm</button>
                    </div>
                </Modal>
            )}

            {/* ── Confirm modal ────────────────────────────────────────────── */}
            {confirmState && (
                <Modal onClose={confirmState.onCancel}>
                    <div>
                        <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>{confirmState.title}</div>
                        <div style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>{confirmState.description}</div>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                        <GhostBtn onClick={confirmState.onCancel}>Cancel</GhostBtn>
                        <button onClick={confirmState.onConfirm} style={{ padding: '8px 18px', borderRadius: 9, background: '#ef4444', color: '#fff', border: 'none', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>
                            {confirmState.confirmLabel || 'Delete'}
                        </button>
                    </div>
                </Modal>
            )}

            {/* ── Profile details modal ────────────────────────────────────── */}
            {managing && (
                <ProfileDetailsModal
                    profile={managing}
                    editable={isAdmin}
                    onClose={() => setManaging(null)}
                    onSaved={async () => { await loadGeneral(); setManaging(null); }}
                    onDelete={() => handleDeleteAccount(managing)}
                    onCopyKey={() => copyKey(managing.id)}
                    onCopyConfig={() => copyConfig(managing.id)}
                    onRegenerateKey={() => handleRegenerateKey(managing)}
                    onConfigure={() => navigate(ROUTES.FORGE_AGENT(managing.id))}
                />
            )}
        </div>
    );
}
