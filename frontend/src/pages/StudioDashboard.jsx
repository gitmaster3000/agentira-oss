import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Folder } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useShellData, projectKey, waitingLink } from '../components/shell/shellData';

// The single "live/running" accent — never used for anything that isn't running
// (COMPONENT_MAP key behavior #5: one accent for run/activity).
const PULSE = 'var(--pulse-blue)';

function timeAgo(iso) {
    if (!iso) return '';
    const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
    if (mins < 1) return 'now';
    if (mins < 60) return `${mins}m`;
    const h = Math.floor(mins / 60);
    if (h < 24) return `${h}h`;
    return `${Math.floor(h / 24)}d`;
}

function fmtDuration(ms) {
    if (ms == null) return '';
    const s = Math.floor(ms / 1000);
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m`;
    return `${Math.floor(m / 60)}h ${m % 60}m`;
}

function fmtTokens(run) {
    const t = (run.input_tokens || 0) + (run.output_tokens || 0) + (run.total_tokens || 0);
    if (!t) return '';
    if (t >= 1000) return `${(t / 1000).toFixed(1)}k tok`;
    return `${t} tok`;
}

function greeting() {
    const h = new Date().getHours();
    if (h < 12) return 'Good morning';
    if (h < 18) return 'Good afternoon';
    return 'Good evening';
}

const initials = (s) => (s || '?').trim().slice(0, 2).toUpperCase();
const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;

const secLabel = { fontSize: '12px', fontWeight: 700, letterSpacing: '.06em', color: 'var(--text-tertiary)' };

/**
 * StudioDashboard — the Home cockpit (prototype `is.home`, design §Home).
 *
 * Per handoff/COMPONENT_MAP.md the Home cockpit loads getProjects · forge.listRuns
 * · getNotifications — all already fetched once by the shell's useShellData() hook
 * (Pulse is global, behavior #2), so we read from there rather than re-querying.
 * Four sections: greeting + summary, LIVE NOW (running runs), NEEDS YOU (runs
 * waiting on a human), YOUR PROJECTS, RECENT ACTIVITY.
 */
export function StudioDashboard() {
    const navigate = useNavigate();
    const { user } = useAuth();
    const {
        projects, runningRuns, runningByProject,
        waitingRuns, recentNotifs, unread, dismissWaiting,
    } = useShellData();

    const runs = runningRuns || [];
    const waiting = waitingRuns || [];
    const projs = projects || [];
    const notifs = (recentNotifs || []).slice(0, 8);

    const projectName = (id) => projs.find((p) => p.id === id)?.name;

    const name = (user?.display_name || user?.name || user?.email || '').trim();
    const firstName = name ? name.split(/[\s@]/)[0] : null;

    // Summary line — built only from the counts we actually have. The "across N
    // projects" scope is a tail clause on real activity, never the whole line:
    // when nothing is live it reads as a calm full phrase, not a fragment.
    let summaryLine;
    if (projs.length === 0) {
        summaryLine = 'No projects yet — create one to get started';
    } else {
        const activity = [];
        if (runs.length) activity.push(`${plural(runs.length, 'agent')} working`);
        if (waiting.length) activity.push(`${plural(waiting.length, 'thing')} need${waiting.length === 1 ? 's' : ''} you`);
        const scope = plural(projs.length, 'project');
        summaryLine = activity.length
            ? `${activity.join(' · ')} across ${scope}`
            : `All quiet across your ${scope}`;
    }

    return (
        <div style={{ padding: '26px 30px', maxWidth: '1000px', width: '100%', fontFamily: 'var(--font-sans)' }}>
            {/* greeting */}
            <h1 style={{ fontSize: '23px', fontWeight: 700, margin: '0 0 3px', color: 'var(--text-primary)' }}>
                {greeting()}{firstName ? `, ${firstName}` : ''}
            </h1>
            <p style={{ fontSize: '13px', color: 'var(--text-muted)', margin: '0 0 22px' }}>{summaryLine}.</p>

            {/* live now / needs you */}
            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1.4fr) minmax(0,1fr)', gap: '16px', marginBottom: '18px' }}>
                {/* LIVE NOW */}
                <div style={{ background: 'var(--surface-raised)', border: '1px solid var(--border-default)', borderRadius: '12px', padding: '15px', minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '13px' }}>
                        <span style={{ position: 'relative', display: 'inline-flex' }}>
                            <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: runs.length ? PULSE : 'var(--text-muted)' }} />
                            {runs.length > 0 && <span style={{ position: 'absolute', inset: 0, borderRadius: '50%', background: PULSE, animation: 'livedot 1.8s ease-out infinite' }} />}
                        </span>
                        <span style={{ fontSize: '12px', fontWeight: 700, letterSpacing: '.04em' }}>LIVE NOW</span>
                        <span style={{ fontSize: '11px', color: 'var(--text-muted)', marginLeft: 'auto' }}>all projects</span>
                    </div>

                    {runs.length === 0 && (
                        <div style={{ fontSize: '12px', color: 'var(--text-muted)', padding: '4px 2px' }}>No agents running right now.</div>
                    )}
                    {runs.map((r) => (
                        <div key={r.id} onClick={() => navigate(`/forge/runs/${r.id}`)} className="agent-active-glow"
                            style={{ borderRadius: '10px', background: 'var(--surface-card)', border: '1px solid var(--border-default)', padding: '11px', marginBottom: '9px', cursor: 'pointer' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '7px' }}>
                                <span style={{ width: '22px', height: '22px', borderRadius: '6px', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(56,189,248,.14)' }}>
                                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke={PULSE} strokeWidth="2"><rect x="3" y="11" width="18" height="10" rx="2" /><circle cx="12" cy="5" r="2" /><path d="M12 7v4" /></svg>
                                </span>
                                <span style={{ fontSize: '12.5px', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.agent_name || 'Agent'}</span>
                                <span style={{ fontSize: '10px', fontWeight: 600, color: '#f1c40f', background: 'rgba(241,196,64,.12)', borderRadius: '5px', padding: '2px 7px', marginLeft: 'auto', flexShrink: 0 }}>RUNNING</span>
                            </div>
                            <div style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginBottom: '8px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {(r.task_key || r.task_id) && <span style={{ fontFamily: 'ui-monospace,monospace', color: 'var(--accent-mono-blue)' }}>{r.task_key || r.task_id}</span>} {r.task_title || r.summary || 'Working…'}
                            </div>
                            <div style={{ display: 'flex', gap: '12px', fontSize: '10.5px', color: 'var(--text-muted)', flexWrap: 'wrap' }}>
                                {(r.project_name || projectName(r.project_id)) && <span>{r.project_name || projectName(r.project_id)}</span>}
                                {r.duration_ms != null && <span>{fmtDuration(r.duration_ms)}</span>}
                                {fmtTokens(r) && <span>{fmtTokens(r)}</span>}
                                {r.cost_usd > 0 && <span style={{ marginLeft: 'auto', color: 'var(--brand-teal)' }}>${r.cost_usd.toFixed(2)}</span>}
                            </div>
                        </div>
                    ))}
                </div>

                {/* NEEDS YOU */}
                <div style={{ background: 'var(--surface-raised)', border: '1px solid var(--border-default)', borderRadius: '12px', padding: '15px', minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '13px' }}>
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#ff9800" strokeWidth="2"><path d="M12 9v4M12 17h.01" /><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /></svg>
                        <span style={{ fontSize: '12px', fontWeight: 700, letterSpacing: '.04em' }}>NEEDS YOU</span>
                        {waiting.length > 0 && (
                            <span style={{ fontSize: '11px', fontWeight: 700, background: '#ff9800', color: '#160c0c', borderRadius: '999px', padding: '1px 7px', marginLeft: 'auto' }}>{waiting.length}</span>
                        )}
                    </div>

                    {waiting.length === 0 && (
                        <div style={{ fontSize: '12px', color: 'var(--text-muted)', padding: '4px 2px' }}>Nothing needs you right now.</div>
                    )}
                    {waiting.map((r) => (
                        <div key={r.id} onClick={() => navigate(waitingLink(r))} className="nav"
                            style={{ display: 'flex', alignItems: 'flex-start', gap: '9px', padding: '8px', borderRadius: '8px', background: 'var(--surface-card)', marginBottom: '7px', cursor: 'pointer' }}>
                            <span style={{ width: '18px', height: '18px', borderRadius: '5px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, marginTop: '1px', background: 'rgba(255,152,0,.14)' }}>
                                <span style={{ width: '8px', height: '8px', borderRadius: '2px', background: '#ff9800' }} />
                            </span>
                            <div style={{ minWidth: 0 }}>
                                <div style={{ fontSize: '12px', color: 'var(--text-primary)', lineHeight: 1.4 }}>{r.agent_name ? `Question from ${r.agent_name}` : 'Waiting on you'}</div>
                                <div style={{ fontSize: '10.5px', color: 'var(--text-muted)', marginTop: '2px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                    {(r.task_key || r.task_id) && <span style={{ fontFamily: 'ui-monospace,monospace', color: 'var(--accent-mono-blue)' }}>{r.task_key || r.task_id}</span>} · {r.task_title || timeAgo(r.created_at) || 'needs your input'}
                                </div>
                            </div>
                            <button type="button" aria-label="Dismiss" title="Dismiss" onClick={(e) => { e.stopPropagation(); dismissWaiting(r.id); }} style={{ marginLeft: 'auto', flexShrink: 0, background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '14px', lineHeight: 1, padding: '0 2px' }}>×</button>
                        </div>
                    ))}
                </div>
            </div>

            {/* YOUR PROJECTS */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
                <span style={{ ...secLabel }}>YOUR PROJECTS</span>
                <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{projs.length}</span>
            </div>
            {projs.length === 0 ? (
                <div style={{ background: 'var(--surface-raised)', border: '1px solid var(--border-default)', borderRadius: '12px', padding: '34px 15px', textAlign: 'center', color: 'var(--text-muted)' }}>
                    <Folder style={{ width: '34px', height: '34px', margin: '0 auto 12px', opacity: 0.4 }} />
                    <p style={{ margin: 0, fontSize: '13px' }}>No projects yet.</p>
                    <p style={{ margin: '8px 0 0', fontSize: '11.5px' }}>Use <b style={{ color: 'var(--brand-lavender)' }}>+ New</b> in the sidebar to create one.</p>
                </div>
            ) : (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: '12px' }}>
                    {projs.map((p) => {
                        const live = runningByProject?.[p.id] || 0;
                        const tasks = p.task_count ?? p.counts?.total;
                        return (
                            <div key={p.id} onClick={() => navigate(`/studio/board/${p.id}`)} className="nav"
                                style={{ background: 'var(--surface-card)', border: '1px solid var(--border-default)', borderRadius: '10px', padding: '13px', cursor: 'pointer' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '9px' }}>
                                    <span style={{ width: '8px', height: '8px', borderRadius: '2px', background: 'var(--accent-primary)', flexShrink: 0 }} />
                                    <span style={{ fontSize: '13.5px', fontWeight: 600, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.name}</span>
                                    <span style={{ fontSize: '9px', fontFamily: 'ui-monospace,monospace', color: 'var(--text-muted)', background: 'var(--surface-base)', borderRadius: '4px', padding: '1px 5px', flexShrink: 0 }}>{p.key_prefix || projectKey(p)}</span>
                                </div>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', fontSize: '11px', color: 'var(--text-muted)', borderTop: '1px solid var(--border-default)', paddingTop: '9px' }}>
                                    {typeof tasks === 'number' && <span>{plural(tasks, 'task')}</span>}
                                    {live > 0 && (
                                        <span style={{ display: 'flex', alignItems: 'center', gap: '4px', color: '#f1c40f', marginLeft: 'auto' }}>
                                            <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: PULSE }} />
                                            {live} running
                                        </span>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}

            {/* RECENT ACTIVITY */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', margin: '26px 0 12px' }}>
                <span style={{ ...secLabel }}>RECENT ACTIVITY</span>
                <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>across workspace</span>
            </div>
            <div style={{ background: 'var(--surface-raised)', border: '1px solid var(--border-default)', borderRadius: '12px', padding: '15px' }}>
                {/* workspace summary — derived from live counts (not a model output) */}
                <div style={{ display: 'flex', gap: '10px', padding: '11px 12px', borderRadius: '10px', background: 'rgba(128,203,196,.06)', border: '1px solid rgba(128,203,196,.18)', marginBottom: notifs.length ? '13px' : 0 }}>
                    <span style={{ width: '22px', height: '22px', borderRadius: '7px', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(128,203,196,.14)' }}>
                        <svg width="13" height="13" viewBox="0 0 24 24" style={{ fill: 'var(--brand-teal)' }} stroke="none"><path d="M12 2l1.9 6.1L20 10l-6.1 1.9L12 18l-1.9-6.1L4 10l6.1-1.9z" /></svg>
                    </span>
                    <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: '10px', fontWeight: 700, letterSpacing: '.08em', color: 'var(--brand-teal)', marginBottom: '4px' }}>SUMMARY</div>
                        <p style={{ fontSize: '12.5px', color: 'var(--text-tertiary)', margin: 0, lineHeight: 1.55, textWrap: 'pretty' }}>
                            {runs.length || waiting.length || unread
                                ? <>Across your workspace: <b style={{ color: 'var(--text-bright)', fontWeight: 600 }}>{plural(runs.length, 'agent')}</b> running, {plural(waiting.length, 'item')} waiting on you, and {plural(unread, 'unread update')} spanning {plural(projs.length, 'project')}.</>
                                : <>All quiet across your {plural(projs.length, 'project')} — no agents running and nothing waiting on you.</>}
                        </p>
                    </div>
                </div>

                {notifs.length === 0 ? (
                    <div style={{ fontSize: '12px', color: 'var(--text-muted)', padding: '4px 2px' }}>No recent activity.</div>
                ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1px' }}>
                        {notifs.map((n) => (
                            <div key={n.id} onClick={() => n.link && navigate(n.link)} className="nav"
                                style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 9px', borderRadius: '8px', cursor: n.link ? 'pointer' : 'default' }}>
                                <span style={{ width: '26px', height: '26px', borderRadius: '50%', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '9.5px', fontWeight: 700, background: 'rgba(128,203,196,.14)', color: 'var(--brand-teal)' }}>{initials(n.type)}</span>
                                <div style={{ flex: 1, minWidth: 0, fontSize: '12.5px', color: 'var(--text-bright)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', opacity: n.read ? 0.6 : 1 }}>
                                    {n.title}
                                    {n.type && <span style={{ color: 'var(--text-muted)' }}> · {n.type}</span>}
                                </div>
                                <span style={{ fontSize: '11px', color: 'var(--text-muted)', flexShrink: 0 }}>{timeAgo(n.created_at)}</span>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}
