import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../context/AuthContext';

// My Work — every task assigned to the current user, across all projects
// (sidebar "My Work"). Data: GET /tasks?assignee=<me>. Task.assignee stores the
// profile name, which is user.name (see backend services._profile_to_dict).
// Grouped by status so the page reads like a personal board.

const priorityColor = (p) => ({
    urgent: '#f87171', high: '#fdd663', medium: '#8ab4f8', low: '#768390',
}[p] || '#768390');

// Present statuses in pipeline order; anything unknown falls to the end.
const STATUS_ORDER = ['in_progress', 'review', 'todo', 'backlog', 'blocked', 'done'];
const statusRank = (s) => {
    const i = STATUS_ORDER.indexOf(s);
    return i === -1 ? STATUS_ORDER.length : i;
};
const prettyStatus = (s) => (s || 'other').replace(/_/g, ' ');

export function MyWork() {
    const navigate = useNavigate();
    const { user } = useAuth();
    const me = user?.name || user?.username || user?.display_name;
    const [tasks, setTasks] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const load = useCallback(async () => {
        if (!me) { setLoading(false); return; }
        try {
            const list = await api.listTasks(null, null, me);
            setTasks(Array.isArray(list) ? list : []);
            setError(null);
        } catch (err) {
            setError(err.message || 'Failed to load your work');
        } finally {
            setLoading(false);
        }
    }, [me]);

    useEffect(() => { load(); }, [load]);

    // Group by status, then order the groups by pipeline position.
    const groups = {};
    for (const t of tasks) {
        const s = t.status || 'other';
        (groups[s] = groups[s] || []).push(t);
    }
    const orderedStatuses = Object.keys(groups).sort((a, b) => statusRank(a) - statusRank(b));

    return (
        <div style={{ maxWidth: '820px', margin: '0 auto', padding: '28px 24px', fontFamily: 'var(--font-sans)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '18px' }}>
                <h1 style={{ fontSize: '22px', fontWeight: 700, color: '#e8ebf0' }}>My Work</h1>
                {!loading && !error && (
                    <span style={{ fontSize: '12px', color: '#768390' }}>{tasks.length} assigned</span>
                )}
            </div>

            {loading && <div style={{ color: '#768390', padding: '40px 0', textAlign: 'center' }}>Loading…</div>}
            {error && <div style={{ color: '#f87171', padding: '40px 0', textAlign: 'center' }}>{error}</div>}
            {!loading && !error && tasks.length === 0 && (
                <div style={{ color: '#768390', padding: '48px 0', textAlign: 'center' }}>Nothing assigned to you yet.</div>
            )}

            {!loading && !error && orderedStatuses.map((status) => (
                <div key={status} style={{ marginBottom: '22px' }}>
                    <div style={{ fontSize: '11.5px', fontWeight: 800, letterSpacing: '.08em', color: '#b1bac4', textTransform: 'uppercase', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span>{prettyStatus(status)}</span>
                        <span style={{ fontSize: '10px', color: '#768390', background: '#1c2128', borderRadius: '999px', padding: '1px 7px' }}>{groups[status].length}</span>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                        {groups[status].map((t) => (
                            <div
                                key={t.id}
                                className="nav"
                                onClick={() => navigate(`/studio/tasks/${t.id}`)}
                                style={{ display: 'flex', alignItems: 'center', gap: '11px', padding: '11px 12px', borderRadius: '10px', cursor: 'pointer', background: '#161b22', border: '1px solid #30363d' }}
                            >
                                <span style={{ width: '7px', height: '7px', borderRadius: '50%', flexShrink: 0, background: priorityColor(t.priority) }} title={t.priority || 'no priority'} />
                                {t.key && <span style={{ fontSize: '11px', color: '#768390', fontFamily: 'ui-monospace,monospace', flexShrink: 0 }}>{t.key}</span>}
                                <span style={{ fontSize: '13.5px', color: '#e8ebf0', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.title}</span>
                                {t.epic_name && <span style={{ fontSize: '11px', color: '#c9b8ff', flexShrink: 0 }}>{t.epic_name}</span>}
                            </div>
                        ))}
                    </div>
                </div>
            ))}
        </div>
    );
}
