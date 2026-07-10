import React from 'react';
import { CircleCheck, AlertTriangle, OctagonAlert, Power, Rocket, Clock, ScrollText } from 'lucide-react';
import { C, MONO, STATUS, statusOf, timeAgo } from './theme';

// The "what's happening and why" line. Agentira's ethos is no black boxes: a
// deployment never just silently changes colour. The backend owns the copy
// (`status_reason`); this is the fallback so the line is never empty.
export function reasonFor(deployment, status) {
    if (deployment?.status_reason) return deployment.status_reason;
    switch (status) {
        case 'live': return 'Running and reachable.';
        case 'building': return deployment?.step
            ? `Building — step ${deployment.step} of ${deployment.total_steps}.`
            : 'Building…';
        case 'queued': return 'Queued — waiting for a build slot.';
        case 'failed': return 'Build failed. Open the logs to see why.';
        case 'crashed': return 'Built, then crashed at runtime. Open the logs to see why.';
        case 'stopped': return 'Preview torn down — redeploy to bring it back.';
        default: return 'No preview deployed for this branch yet — deploy one to test it.';
    }
}

const TONE = {
    live: { color: C.goodText, bg: 'rgba(46,204,113,.06)', border: 'rgba(46,204,113,.22)', icon: CircleCheck },
    building: { color: C.infoText, bg: 'rgba(56,189,248,.06)', border: 'rgba(56,189,248,.22)', icon: Rocket },
    queued: { color: C.infoText, bg: 'rgba(56,189,248,.06)', border: 'rgba(56,189,248,.22)', icon: Clock },
    failed: { color: C.badText, bg: 'rgba(248,81,73,.06)', border: 'rgba(248,81,73,.22)', icon: AlertTriangle },
    crashed: { color: C.badText, bg: 'rgba(248,81,73,.06)', border: 'rgba(248,81,73,.22)', icon: OctagonAlert },
    stopped: { color: C.textMuted, bg: '#131720', border: C.border, icon: Power },
    none: { color: C.textMuted, bg: C.raised, border: C.border, icon: Rocket },
};

const PLACEHOLDER = {
    live: ['Your app, running', 'Live interactive preview renders here · click straight through to test'],
    building: ['Building preview…', 'Your app will appear here the moment the build finishes'],
    queued: ['Queued', 'Waiting for a build slot — this page is polling'],
    failed: ['Build failed', 'Fix the error and push to retry, or open the logs'],
    crashed: ['App crashed', 'It built, then died at runtime — open the logs'],
    stopped: ['Preview stopped', 'Torn down — redeploy to test again'],
    none: ['No preview yet', 'Deploy a preview to test this branch before merge'],
};

function Placeholder({ status }) {
    const tone = TONE[status] || TONE.none;
    const Icon = tone.icon;
    const [title, sub] = PLACEHOLDER[status] || PLACEHOLDER.none;
    const color = STATUS[status]?.color || C.textDim;
    return (
        <div className="dp-stripe" style={{ height: 380, position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12, backgroundColor: '#0d1016' }}>
            <div style={{ width: 40, height: 40, borderRadius: 11, background: tone.bg, border: `1px solid ${tone.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Icon className="w-5 h-5" style={{ color }} strokeWidth={1.8} />
            </div>
            <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 12.5, fontWeight: 600, color: '#c8cdd4' }}>{title}</div>
                <div style={{ fontSize: 10.5, color: C.textFaint, marginTop: 3 }}>{sub}</div>
            </div>
        </div>
    );
}

/**
 * The hero: a browser chrome around the running app, then the commit that
 * produced it, then the plain-language reason line.
 */
export function LivePreview({ entry, onOpenLogs }) {
    const d = entry.deployment;
    const status = statusOf(d);
    const tone = TONE[status] || TONE.none;
    const ToneIcon = tone.icon;
    const url = d?.url;
    const failed = status === 'failed' || status === 'crashed';

    return (
        <div style={{ marginBottom: 20 }}>
            <div style={{ borderRadius: 12, border: `1px solid ${C.border}`, overflow: 'hidden', background: C.void }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 11px', background: C.surface, borderBottom: `1px solid ${C.borderSoft}` }}>
                    <span style={{ display: 'flex', gap: 5 }}>
                        <span style={{ width: 9, height: 9, borderRadius: '50%', background: C.bad }} />
                        <span style={{ width: 9, height: 9, borderRadius: '50%', background: C.warn }} />
                        <span style={{ width: 9, height: 9, borderRadius: '50%', background: C.good }} />
                    </span>
                    <span style={{ flex: 1, fontFamily: MONO, fontSize: 10.5, color: C.textDim, background: C.bg, border: `1px solid ${C.borderSoft}`, borderRadius: 6, padding: '3px 9px', textAlign: 'center', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {url || '—'}
                    </span>
                    {status === 'live' && (
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 9.5, color: C.info, background: 'rgba(56,189,248,.1)', borderRadius: 6, padding: '3px 8px' }}>
                            <span className="dp-blink" style={{ width: 5, height: 5, borderRadius: '50%', background: C.info }} />
                            embedded preview
                        </span>
                    )}
                </div>

                {status === 'live' && url ? (
                    <iframe
                        title={`${entry.branch} preview`}
                        src={url}
                        sandbox="allow-scripts allow-forms allow-same-origin allow-popups"
                        style={{ display: 'block', width: '100%', height: 380, border: 'none', background: '#fff' }}
                    />
                ) : (
                    <Placeholder status={status} />
                )}
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 14, flexWrap: 'wrap' }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 11.5, color: '#c8cdd4' }}>
                    <span style={{ fontFamily: MONO, color: '#7c8db5', background: C.bg, border: `1px solid ${C.border}`, borderRadius: 5, padding: '2px 7px' }}>
                        {(entry.commit_sha || '').slice(0, 7) || '—'}
                    </span>
                    {entry.commit_message}
                </span>
                <span style={{ width: 4, height: 4, borderRadius: '50%', background: '#3a4048' }} />
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11, color: C.textDim }}>
                    {entry.author_is_agent && (
                        <span style={{ width: 17, height: 17, borderRadius: '50%', background: 'rgba(0,188,212,.16)', color: '#00bcd4', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 7.5, fontWeight: 700 }}>AI</span>
                    )}
                    {d?.trigger === 'manual' ? 'redeployed' : 'pushed'} by {entry.author} · {timeAgo(d?.updated_at || entry.committed_at)}
                </span>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12, padding: '9px 12px', borderRadius: 9, background: tone.bg, border: `1px solid ${tone.border}` }}>
                <ToneIcon className="w-3.5 h-3.5" style={{ color: tone.color, flexShrink: 0 }} strokeWidth={2} />
                <span style={{ fontSize: 11.5, color: tone.color, flex: 1 }}>{reasonFor(d, status)}</span>
                {d && (
                    <button
                        onClick={() => onOpenLogs(d.id)}
                        style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, fontWeight: 600, color: failed ? C.bad : C.textMuted, background: 'transparent', border: `1px solid ${failed ? 'rgba(248,81,73,.35)' : C.border}`, borderRadius: 7, padding: '4px 9px', cursor: 'pointer', fontFamily: 'inherit', flexShrink: 0 }}
                    >
                        <ScrollText className="w-3 h-3" />
                        View logs
                    </button>
                )}
            </div>
        </div>
    );
}
