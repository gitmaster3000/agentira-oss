import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../../api';

const AUTH_LABELS = {
    agent_key: "The agent's own Agentira login",
    bearer: 'A token I paste',
    none: 'No login',
};

const box = { border: '1px solid var(--border-subtle)', borderRadius: 10, padding: 12, background: 'var(--surface-card)' };
const input = { width: '100%', padding: '7px 9px', borderRadius: 8, border: '1px solid var(--border-default)', background: 'transparent', color: 'var(--text-primary)', fontSize: 12.5 };
const btn = { padding: '5px 10px', borderRadius: 8, border: '1px solid var(--border-default)', background: 'transparent', color: 'var(--text-secondary)', fontSize: 12, cursor: 'pointer' };
const primary = { ...btn, background: 'var(--accent-primary)', color: 'var(--accent-on)', border: 'none', fontWeight: 600 };

const statusText = (s) => (s.status === 'ok' ? `Connected · ${s.tools.length} tools` : s.status === 'error' ? s.status_detail || 'Could not connect' : 'Not tested yet');
const statusColor = (s) => (s.status === 'ok' ? '#2ecc71' : s.status === 'error' ? '#f87171' : 'var(--text-muted)');

function ServerRow({ server, onChange }) {
    const [open, setOpen] = useState(false);
    const [busy, setBusy] = useState(false);
    const run = async (fn) => {
        setBusy(true);
        try { onChange(await fn()); } catch (e) { alert(e.message); } finally { setBusy(false); }
    };
    return (
        <div style={{ ...box, opacity: server.enabled ? 1 : 0.6 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span style={{ width: 8, height: 8, borderRadius: 4, background: statusColor(server) }} />
                <strong style={{ fontSize: 13, color: 'var(--text-primary)' }}>{server.name}</strong>
                <span style={{ fontSize: 12, color: statusColor(server), flex: 1, minWidth: 120 }}>{statusText(server)}</span>
                <button style={btn} disabled={busy} onClick={() => run(() => api.forge.testMcpServer(server.id))}>Test</button>
                <button style={btn} disabled={busy} onClick={() => run(() => api.forge.updateMcpServer(server.id, { enabled: !server.enabled }))}>{server.enabled ? 'Turn off' : 'Turn on'}</button>
                <button style={btn} disabled={busy} onClick={() => { if (window.confirm(`Remove ${server.name}? Agents lose access to it.`)) run(async () => { await api.forge.deleteMcpServer(server.id); return null; }); }}>Remove</button>
            </div>
            <div style={{ fontSize: 11.5, color: 'var(--text-muted)', marginTop: 4 }}>
                {server.description || server.url} · Signs in with {AUTH_LABELS[server.auth_mode].toLowerCase()}
            </div>
            {server.tools.length > 0 && (
                <>
                    <button style={{ ...btn, border: 'none', padding: '6px 0 0', color: 'var(--accent-primary)' }} onClick={() => setOpen(!open)}>
                        {open ? 'Hide tools' : 'Show tools'}
                    </button>
                    {open && server.tools.map((t) => (
                        <div key={t.name} style={{ fontSize: 12, marginTop: 4, color: 'var(--text-secondary)' }}>
                            <code>{t.name}</code> <span style={{ color: 'var(--text-muted)' }}>{t.read_only ? '· read-only' : '· can change things'}</span>
                            {t.description && <div style={{ color: 'var(--text-muted)', fontSize: 11.5 }}>{t.description}</div>}
                        </div>
                    ))}
                </>
            )}
        </div>
    );
}

export function McpServersPanel({ ezineUrl }) {
    const [servers, setServers] = useState(null);
    const [form, setForm] = useState(null);
    const [err, setErr] = useState('');
    const [busy, setBusy] = useState(false);

    const load = useCallback(() => api.forge.listMcpRegistry().then(setServers).catch((e) => setErr(e.message)), []);
    useEffect(() => { load(); }, [load]);

    const upsert = (row, id) => setServers((cur) => (row ? cur.map((s) => (s.id === id ? row : s)) : cur.filter((s) => s.id !== id)));

    const submit = async () => {
        setBusy(true); setErr('');
        try {
            const created = await api.forge.addMcpServer(form);
            setServers((cur) => [...(cur || []), created]);
            setForm(null);
        } catch (e) { setErr(e.message); } finally { setBusy(false); }
    };

    const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

    return (
        <div style={{ marginTop: 32 }}>
            <h3 style={{ fontSize: 15, fontWeight: 600, margin: '0 0 4px', color: 'var(--text-primary)' }}>Tools for your agents</h3>
            <p style={{ fontSize: 12.5, color: 'var(--text-muted)', margin: '0 0 14px' }}>
                Connect an app once, then switch it on per agent. Agents can only use the tools you allow.
            </p>
            {err && <div style={{ fontSize: 12.5, color: '#f87171', marginBottom: 8 }}>{err}</div>}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {servers === null && <div style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>Loading…</div>}
                {servers?.length === 0 && <div style={{ fontSize: 12.5, color: 'var(--text-muted)', fontStyle: 'italic' }}>Nothing connected yet.</div>}
                {servers?.map((s) => <ServerRow key={s.id} server={s} onChange={(row) => upsert(row, s.id)} />)}
            </div>

            {form ? (
                <div style={{ ...box, marginTop: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
                    <input style={input} placeholder="Name (e.g. ezine)" value={form.name} onChange={set('name')} />
                    <input style={input} placeholder="Address (https://…/mcp)" value={form.url} onChange={set('url')} />
                    <input style={input} placeholder="What it is for (optional)" value={form.description} onChange={set('description')} />
                    <select style={input} value={form.auth_mode} onChange={set('auth_mode')}>
                        {Object.entries(AUTH_LABELS).map(([k, v]) => <option key={k} value={k}>Sign in with: {v}</option>)}
                    </select>
                    {form.auth_mode === 'bearer' && <input style={input} type="password" placeholder="Token" value={form.token} onChange={set('token')} />}
                    <div style={{ display: 'flex', gap: 8 }}>
                        <button style={primary} disabled={busy || !form.name || !form.url} onClick={submit}>{busy ? 'Connecting…' : 'Connect & find tools'}</button>
                        <button style={btn} onClick={() => { setForm(null); setErr(''); }}>Cancel</button>
                    </div>
                </div>
            ) : (
                <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                    <button style={primary} onClick={() => setForm({ name: '', url: '', description: '', auth_mode: 'agent_key', token: '' })}>Add a server</button>
                    {!servers?.some((s) => s.name === 'ezine') && (
                        <button style={btn} onClick={() => setForm({ name: 'ezine', url: ezineUrl, description: 'Read prototypes, docs and comments', auth_mode: 'agent_key', token: '' })}>Add Ezine</button>
                    )}
                </div>
            )}
        </div>
    );
}
