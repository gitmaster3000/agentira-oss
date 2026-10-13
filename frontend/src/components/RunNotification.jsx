import React from 'react';

// Rich rendering of run notifications. Backend sends `meta`
// ({status, agent_name, task_key, task_title, project_name, model,
// duration_ms, cost_usd, pr_url, error}); rows without it fall back to `title`.

const STATUS = {
    created:   { verb: 'was assigned a run',  pill: 'Queued',           color: 'var(--text-tertiary)' },
    ready:     { verb: 'is ready to start',   pill: 'Ready',            color: '#fbbf24' },
    running:   { verb: 'started working',     pill: '● Running',        color: 'var(--brand-lavender)' },
    completed: { verb: 'finished a task',     pill: '✓ Completed',      color: '#81c995' },
    failed:    { verb: 'run failed',          pill: '✕ Failed',         color: '#f87171' },
};

export function isRunMeta(meta) {
    return !!(meta && meta.kind === 'run' && STATUS[meta.status]);
}

export function fmtDuration(ms) {
    if (ms == null) return '';
    const s = Math.round(ms / 1000);
    if (s < 60) return `${s}s`;
    return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`;
}

function prLabel(url) {
    const m = /\/pull\/(\d+)/.exec(url || '');
    return m ? `PR #${m[1]}` : 'PR';
}

const pillStyle = (color) => ({
    fontSize: '11px', padding: '2px 8px', borderRadius: '999px', whiteSpace: 'nowrap',
    border: `1px solid ${color || 'var(--border-default)'}`, color: color || 'var(--text-tertiary)',
});

function Pill({ color, children }) {
    return <span style={pillStyle(color)}>{children}</span>;
}

function Avatar({ name }) {
    const initials = (name || '?').split(/[\s_-]+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase();
    return (
        <span style={{ width: 32, height: 32, borderRadius: '50%', background: 'var(--overlay-tint)', display: 'grid', placeItems: 'center', fontWeight: 700, fontSize: 13, flexShrink: 0 }}>
            {initials}
        </span>
    );
}

// Option A — Inbox card: headline, task line, pills, inline failure reason.
export function RunNotificationCard({ meta, read }) {
    const st = STATUS[meta.status];
    const done = meta.status === 'completed' || meta.status === 'failed';
    return (
        <>
            <Avatar name={meta.agent_name} />
            <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: '13.5px', fontWeight: read ? 400 : 600, color: read ? 'var(--text-tertiary)' : 'var(--text-bright)' }}>
                    <b style={{ color: 'var(--brand-lavender)' }}>{meta.agent_name}</b> {st.verb}
                </div>
                {(meta.task_key || meta.task_title) && (
                    <div style={{ fontSize: '13px', marginTop: 3, color: 'var(--text-secondary)' }}>
                        {meta.task_key && <span style={{ color: '#8ab4f8', fontWeight: 600, marginRight: 6 }}>{meta.task_key}</span>}
                        {meta.task_title}
                    </div>
                )}
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
                    <Pill color={st.color}>{st.pill}</Pill>
                    {meta.project_name && <Pill>{meta.project_name}</Pill>}
                    {!done && meta.model && <Pill>{meta.model}</Pill>}
                    {done && meta.duration_ms != null && <Pill>{fmtDuration(meta.duration_ms)}</Pill>}
                    {done && meta.cost_usd > 0 && <Pill>{`$${meta.cost_usd.toFixed(2)}`}</Pill>}
                    {done && meta.pr_url && <Pill>{prLabel(meta.pr_url)}</Pill>}
                </div>
                {meta.error && (
                    <div style={{ marginTop: 6, fontSize: '12.5px', color: '#f5b0b0', borderLeft: '2px solid #f87171', background: 'rgba(248,113,113,.06)', padding: '4px 8px' }}>
                        {meta.error}
                    </div>
                )}
            </div>
        </>
    );
}

// Option B — compact one-liner for the bell / peek.
export function RunNotificationLine({ meta }) {
    const st = STATUS[meta.status];
    return (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0, fontSize: '12.5px', overflow: 'hidden', whiteSpace: 'nowrap' }}>
            <b style={{ color: 'var(--brand-lavender)' }}>{meta.agent_name}</b>
            <Pill color={st.color}>{st.pill}</Pill>
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', color: 'var(--text-bright)' }}>
                {meta.task_key && <span style={{ color: '#8ab4f8', fontWeight: 600, marginRight: 4 }}>{meta.task_key}</span>}
                {meta.task_title}
            </span>
        </div>
    );
}
