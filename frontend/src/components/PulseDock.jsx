import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useShellData } from './shell/shellData';

// The single "live/running" accent — never used for anything that isn't running.
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

const initials = (s) => (s || '?').trim().slice(0, 2).toUpperCase();
const secLabel = { fontSize: '10px', fontWeight: 700, letterSpacing: '.1em', color: 'var(--text-muted)' };

/**
 * PulseDock — the always-mounted Pulse drawer (port of the prototype's
 * full-height right rail). Toggled by the top-bar pill via shared ShellData,
 * so the pill and the drawer are one source (COMPONENT_MAP key behavior #2).
 * Three live sections: RUNNING (the live runs), WAITING ON YOU (runs paused
 * for a human), and RECENT activity. An on-demand slide-over: opened from the
 * top-bar pill, it slides in as a fixed right-side overlay over a dim backdrop
 * (floats over the page, never resizes it) and is dismissed by clicking the
 * backdrop. Pulse blue appears ONLY for actually-running work.
 */
export function PulseDock() {
    const { pulseOpen, togglePulse, runningRuns, waitingRuns, recentNotifs } = useShellData();
    const navigate = useNavigate();

    if (!pulseOpen) return null;

    const runs = runningRuns || [];
    const waiting = waitingRuns || [];
    const notifs = (recentNotifs || []).slice(0, 6);

    return (
        <>
        {/* Dim backdrop — makes it read as floating OVER the page (not a pushed
            sidebar); click to dismiss. */}
        <div onClick={togglePulse} style={{ position: 'fixed', inset: 0, zIndex: 44, background: 'rgba(0,0,0,.45)', animation: 'pulseFade .2s ease' }} />
        <aside style={{ position: 'fixed', top: 'calc(64px + var(--app-top-offset, 0px))', right: '12px', bottom: '12px', width: '300px', zIndex: 45, border: '1px solid var(--overlay-tint)', borderRadius: '16px', background: 'var(--surface-raised)', display: 'flex', flexDirection: 'column', fontFamily: 'var(--font-sans)', boxShadow: '0 16px 48px rgba(0,0,0,.5)', overflow: 'hidden', animation: 'pulseSlideIn .22s ease' }}>
            {/* header */}
            <div style={{ height: '54px', flexShrink: 0, boxSizing: 'border-box', display: 'flex', alignItems: 'center', gap: '9px', padding: '0 16px', borderBottom: '1px solid var(--border-default)' }}>
                <span style={{ position: 'relative', display: 'inline-flex' }}>
                    <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: runs.length ? PULSE : 'var(--text-muted)' }} />
                    {runs.length > 0 && <span style={{ position: 'absolute', inset: 0, borderRadius: '50%', background: PULSE, animation: 'livedot 1.8s ease-out infinite' }} />}
                </span>
                <span style={{ fontSize: '12.5px', fontWeight: 700, letterSpacing: '.06em', flex: 1 }}>PULSE</span>
                <div className="nav" onClick={togglePulse} title="Hide Pulse" style={{ width: '28px', height: '28px', borderRadius: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', cursor: 'pointer' }}>
                    <svg className="ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6 6 18M6 6l12 12" /></svg>
                </div>
            </div>

            {/* body — the three sections always show, so it's clear what Pulse
                tracks even when each is empty. */}
            <div style={{ flex: 1, overflowY: 'auto', padding: '12px' }}>
                <div style={{ ...secLabel, marginBottom: '9px' }}>RUNNING · {runs.length}</div>
                {runs.length === 0 && <EmptyRow>No agents running right now.</EmptyRow>}
                {runs.length > 0 && (
                    <>
                        {runs.map((r) => (
                            <div key={r.id} className="nav" onClick={() => navigate(`/forge/runs/${r.id}`)} style={{ borderRadius: '9px', background: 'var(--surface-card)', border: '1px solid var(--border-default)', padding: '10px', marginBottom: '8px', cursor: 'pointer' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '7px', marginBottom: '6px' }}>
                                    <span style={{ width: '7px', height: '7px', borderRadius: '50%', background: PULSE }} />
                                    <span style={{ fontSize: '12px', fontWeight: 600, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.agent_name || 'Agent'}</span>
                                    {r.cost_usd > 0 && <span style={{ fontSize: '10px', color: 'var(--brand-teal)' }}>${r.cost_usd.toFixed(2)}</span>}
                                </div>
                                <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginBottom: '7px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                    {(r.task_key || r.task_id) && <span style={{ fontFamily: 'ui-monospace,monospace', color: 'var(--accent-mono-blue)' }}>{r.task_key || r.task_id}</span>} {r.task_title || r.summary || 'Working…'}
                                </div>
                                <div style={{ height: '3px', borderRadius: '999px', background: 'rgba(56,189,248,.1)', overflow: 'hidden', position: 'relative' }}>
                                    <span style={{ position: 'absolute', top: 0, height: '100%', width: '35%', borderRadius: '999px', background: 'linear-gradient(90deg,rgba(56,189,248,0),var(--pulse-blue),var(--pulse-blue-bright))', animation: 'barwork 1.5s ease-in-out infinite' }} />
                                </div>
                            </div>
                        ))}
                    </>
                )}

                <div style={{ ...secLabel, margin: '16px 0 9px' }}>WAITING ON YOU · {waiting.length}</div>
                {waiting.length === 0 && <EmptyRow>Nothing needs you right now.</EmptyRow>}
                {waiting.length > 0 && (
                    <>
                        {waiting.map((r) => (
                            <div key={r.id} className="nav" onClick={() => navigate(`/forge/runs/${r.id}`)} style={{ borderRadius: '9px', background: 'var(--surface-card)', border: '1px solid rgba(255,152,0,.3)', padding: '10px', marginBottom: '8px', cursor: 'pointer' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '7px', marginBottom: '5px' }}>
                                    <svg className="ico" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#ff9800" strokeWidth="2"><path d="M12 9v4M12 17h.01" /><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /></svg>
                                    <span style={{ fontSize: '12px', fontWeight: 600, color: '#ffb74d', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.agent_name ? `Question from ${r.agent_name}` : 'Waiting on you'}</span>
                                </div>
                                <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                    {(r.task_key || r.task_id) && <span style={{ fontFamily: 'ui-monospace,monospace', color: 'var(--accent-mono-blue)' }}>{r.task_key || r.task_id}</span>} {r.task_title || 'Needs your input'}
                                </div>
                            </div>
                        ))}
                    </>
                )}

                <div style={{ ...secLabel, margin: '16px 0 9px' }}>RECENT ACTIVITY</div>
                {notifs.length === 0 && <EmptyRow>No recent activity.</EmptyRow>}
                {notifs.length > 0 && (
                    <>
                        {notifs.map((n) => (
                            <div key={n.id} className="nav" onClick={() => n.link && navigate(n.link)} style={{ borderRadius: '9px', padding: '9px', marginBottom: '2px', cursor: n.link ? 'pointer' : 'default' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '7px', marginBottom: '3px' }}>
                                    <span style={{ width: '18px', height: '18px', borderRadius: '50%', background: 'rgba(128,203,196,.14)', color: 'var(--brand-teal)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '9px', fontWeight: 700, flexShrink: 0 }}>{initials(n.type)}</span>
                                    <span style={{ fontSize: '11.5px', fontWeight: 600, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', opacity: n.read ? 0.6 : 1 }}>{n.title}</span>
                                    <span style={{ fontSize: '10px', color: 'var(--text-muted)', flexShrink: 0 }}>{timeAgo(n.created_at)}</span>
                                </div>
                                {n.type && <div style={{ fontSize: '11px', color: 'var(--text-muted)', paddingLeft: '25px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{n.type}</div>}
                            </div>
                        ))}
                    </>
                )}
            </div>
        </aside>
        </>
    );
}

function EmptyRow({ children }) {
    return (
        <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', padding: '6px 2px 2px', lineHeight: 1.5 }}>
            {children}
        </div>
    );
}
