import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';

// Inbox — the full-page notification centre (sidebar "Inbox"). The topbar/Pulse
// bells show a peek; this is the complete list with read/unread filtering and
// mark-as-read. Data: GET /notifications?unread_only=false, PATCH /:id/read.
// Notification shape (backend services.list_notifications): {id, type, title,
// link, read, created_at}. `link` is a backend path like /tasks/:id — normalise
// it to the studio route the SPA actually serves.

function timeAgo(iso) {
    if (!iso) return '';
    const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
    if (mins < 1) return 'now';
    if (mins < 60) return `${mins}m`;
    const h = Math.floor(mins / 60);
    if (h < 24) return `${h}h`;
    return `${Math.floor(h / 24)}d`;
}

// Backend links are bare (/tasks/:id, /projects/:id); the router serves them
// under /studio. Map to a real route so the row actually navigates.
function studioLink(link) {
    if (!link) return null;
    const task = link.match(/^\/tasks\/(.+)$/);
    if (task) return `/studio/tasks/${task[1]}`;
    const proj = link.match(/^\/projects\/(.+)$/);
    if (proj) return `/studio/project/${proj[1]}/overview`;
    return link;
}

const typeColor = (t) => {
    if (/reject|fail|error/i.test(t)) return '#f87171';
    if (/assign|dispatch|run/i.test(t)) return 'var(--brand-lavender)';
    if (/complete|done|success|approve/i.test(t)) return '#81c995';
    return 'var(--pulse-blue)';
};

export function Inbox() {
    const navigate = useNavigate();
    const [notifs, setNotifs] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [filter, setFilter] = useState('all'); // 'all' | 'unread'

    const load = useCallback(async () => {
        try {
            const list = await api.getNotifications(false);
            setNotifs(Array.isArray(list) ? list : []);
            setError(null);
        } catch (err) {
            setError(err.message || 'Failed to load inbox');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const openNotif = async (n) => {
        if (!n.read) {
            setNotifs((prev) => prev.map((x) => (x.id === n.id ? { ...x, read: true } : x)));
            await api.markNotificationRead(n.id).catch(() => {});
        }
        const to = studioLink(n.link);
        if (to) navigate(to);
    };

    const markAllRead = async () => {
        const unread = notifs.filter((n) => !n.read);
        if (unread.length === 0) return;
        setNotifs((prev) => prev.map((x) => ({ ...x, read: true })));
        await Promise.all(unread.map((n) => api.markNotificationRead(n.id).catch(() => {})));
    };

    const unreadCount = notifs.filter((n) => !n.read).length;
    const shown = filter === 'unread' ? notifs.filter((n) => !n.read) : notifs;

    const tab = (key, label) => (
        <button
            onClick={() => setFilter(key)}
            style={{
                fontSize: '13px', padding: '5px 12px', borderRadius: '8px', cursor: 'pointer',
                border: '1px solid ' + (filter === key ? 'var(--brand-lavender)' : 'var(--border-default)'),
                background: filter === key ? 'rgba(201,184,255,.10)' : 'transparent',
                color: filter === key ? 'var(--brand-lavender)' : 'var(--text-tertiary)', fontWeight: filter === key ? 600 : 400,
            }}
        >
            {label}
        </button>
    );

    return (
        <div style={{ maxWidth: '760px', margin: '0 auto', padding: '28px 24px', fontFamily: 'var(--font-sans)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '18px' }}>
                <h1 style={{ fontSize: '22px', fontWeight: 700, color: 'var(--text-bright)' }}>Inbox</h1>
                {unreadCount > 0 && (
                    <span style={{ fontSize: '11px', fontWeight: 700, background: '#ef4444', color: '#fff', borderRadius: '999px', padding: '2px 8px' }}>{unreadCount}</span>
                )}
                <div style={{ flex: 1 }} />
                {unreadCount > 0 && (
                    <button onClick={markAllRead} style={{ fontSize: '12.5px', color: '#8ab4f8', background: 'transparent', border: 'none', cursor: 'pointer' }}>
                        Mark all read
                    </button>
                )}
            </div>

            <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
                {tab('all', 'All')}
                {tab('unread', `Unread${unreadCount > 0 ? ` (${unreadCount})` : ''}`)}
            </div>

            {loading && <div style={{ color: 'var(--text-muted)', padding: '40px 0', textAlign: 'center' }}>Loading…</div>}
            {error && <div style={{ color: '#f87171', padding: '40px 0', textAlign: 'center' }}>{error}</div>}
            {!loading && !error && shown.length === 0 && (
                <div style={{ color: 'var(--text-muted)', padding: '48px 0', textAlign: 'center' }}>
                    {filter === 'unread' ? 'No unread notifications.' : 'Your inbox is empty.'}
                </div>
            )}

            {!loading && !error && shown.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                    {shown.map((n) => (
                        <div
                            key={n.id}
                            className="nav"
                            onClick={() => openNotif(n)}
                            style={{
                                display: 'flex', alignItems: 'flex-start', gap: '11px', padding: '12px 12px',
                                borderRadius: '10px', cursor: 'pointer',
                                background: n.read ? 'transparent' : 'rgba(56,189,248,.05)',
                                border: '1px solid ' + (n.read ? 'transparent' : 'rgba(56,189,248,.18)'),
                            }}
                        >
                            <span style={{ width: '8px', height: '8px', borderRadius: '50%', flexShrink: 0, marginTop: '5px', background: n.read ? 'var(--border-default)' : typeColor(n.type) }} />
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontSize: '13.5px', color: n.read ? 'var(--text-tertiary)' : 'var(--text-bright)', fontWeight: n.read ? 400 : 600, lineHeight: 1.35 }}>{n.title}</div>
                                {n.type && <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>{n.type}</div>}
                            </div>
                            <span style={{ fontSize: '11px', color: 'var(--text-muted)', flexShrink: 0, marginTop: '2px' }}>{timeAgo(n.created_at)}</span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
