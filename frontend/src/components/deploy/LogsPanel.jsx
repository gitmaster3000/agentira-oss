import React, { useCallback, useEffect, useRef, useState } from 'react';
import { X, Copy, Check } from 'lucide-react';
import { api } from '../../api';
import { C, MONO, IN_FLIGHT, statusOf, timeAgo } from './theme';
import { StatusPill } from './StatusPill';

const LEVEL_COLOR = { error: C.bad, warn: C.warn, info: C.textMuted, debug: C.textFaint };
const MAX_LOG_LINES = 300; // Perf fix for AP-433: prevent unbounded growth during long builds that makes UI slow / high mem

// Timeline of the deployment's own history, so a red state has a story.
function Timeline({ events }) {
    if (!events?.length) return null;
    return (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, padding: '10px 16px', borderBottom: `1px solid ${C.borderSoft}` }}>
            {events.map((e, i) => (
                <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 10.5, color: C.textDim }}>
                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: e.status === 'failed' || e.status === 'crashed' ? C.bad : e.status === 'live' ? C.good : C.info }} />
                    {e.status} · {timeAgo(e.at)}
                </span>
            ))}
        </div>
    );
}

/**
 * Deployment detail. Where the user goes when something's red: streamed logs in
 * their own scroll container, copyable, with the status timeline above them.
 * Polls with a cursor while the deployment is still in flight.
 */
export function LogsPanel({ projectId, deployment, onClose }) {
    const [lines, setLines] = useState([]);
    const [cursor, setCursor] = useState(0);
    const [copied, setCopied] = useState(false);
    const [error, setError] = useState(null);
    const scrollRef = useRef(null);
    const cursorRef = useRef(0);
    const status = statusOf(deployment);

    const fetchLogs = useCallback(async () => {
        try {
            const res = await api.getDeploymentLogs(projectId, deployment.id, cursorRef.current);
            if (res.lines?.length) {
                setLines(prev => {
                    const next = [...prev, ...res.lines];
                    // Cap to keep memory + render cost low even for very long running deploys
                    return next.length > MAX_LOG_LINES ? next.slice(next.length - MAX_LOG_LINES) : next;
                });
                cursorRef.current = res.next_cursor;
                setCursor(res.next_cursor);
            }
            setError(null);
        } catch (err) {
            setError(err.message);
        }
    }, [projectId, deployment.id]);

    useEffect(() => {
        fetchLogs();
        if (!IN_FLIGHT.has(status)) return undefined;
        const t = setInterval(fetchLogs, 3000);
        return () => clearInterval(t);
    }, [fetchLogs, status]);

    // Follow the tail while new lines stream in.
    useEffect(() => {
        const el = scrollRef.current;
        if (el) el.scrollTop = el.scrollHeight;
    }, [cursor]);

    const copy = async () => {
        await navigator.clipboard.writeText(lines.map(l => l.text).join('\n'));
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
    };

    return (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
            <div role="dialog" aria-label="Deployment logs" style={{ width: 'min(880px, 92vw)', maxHeight: '84vh', display: 'flex', flexDirection: 'column', background: C.panel, border: `1px solid ${C.border}`, borderRadius: 14, overflow: 'hidden', boxShadow: '0 18px 44px rgba(0,0,0,.55)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', borderBottom: `1px solid ${C.border}` }}>
                    <span style={{ fontFamily: MONO, fontSize: 13, fontWeight: 600, color: C.text }}>{deployment.branch}</span>
                    <StatusPill status={status} detail={status === 'building' && deployment.step ? `${deployment.step}/${deployment.total_steps}` : undefined} />
                    <span style={{ fontFamily: MONO, fontSize: 11, color: C.textDim }}>{(deployment.commit_sha || '').slice(0, 7)}</span>
                    <div style={{ flex: 1 }} />
                    {deployment.url && (
                        <a href={deployment.url} target="_blank" rel="noreferrer" style={{ fontFamily: MONO, fontSize: 11, color: C.infoText, textDecoration: 'none' }}>{deployment.url}</a>
                    )}
                    <button onClick={copy} title="Copy logs" style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, color: C.textMuted, background: 'transparent', border: `1px solid ${C.border}`, borderRadius: 7, padding: '5px 9px', cursor: 'pointer', fontFamily: 'inherit' }}>
                        {copied ? <Check className="w-3 h-3" style={{ color: C.good }} /> : <Copy className="w-3 h-3" />}
                        {copied ? 'Copied' : 'Copy'}
                    </button>
                    <button onClick={onClose} aria-label="Close logs" style={{ background: 'transparent', border: 'none', color: C.textDim, cursor: 'pointer', display: 'flex' }}>
                        <X className="w-4 h-4" />
                    </button>
                </div>

                <Timeline events={deployment.events} />

                <div
                    ref={scrollRef}
                    style={{ flex: 1, overflowY: 'auto', background: C.void, padding: '12px 16px', fontFamily: MONO, fontSize: 11.5, lineHeight: 1.65, minHeight: 260 }}
                >
                    {lines.length === 0 && !error && (
                        <div style={{ color: C.textFaint }}>{IN_FLIGHT.has(status) ? 'Waiting for output…' : 'No logs for this deployment.'}</div>
                    )}
                    {error && <div style={{ color: C.bad }}>Could not load logs: {error}</div>}
                    {lines.map((l, i) => (
                        <div key={i} style={{ display: 'flex', gap: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                            <span style={{ color: C.textFaint, flexShrink: 0 }}>{String(i + 1).padStart(4, ' ')}</span>
                            <span style={{ color: LEVEL_COLOR[l.level] || C.textMuted }}>{l.text}</span>
                        </div>
                    ))}
                    {IN_FLIGHT.has(status) && lines.length > 0 && (
                        <div style={{ color: C.info, marginTop: 6 }}>
                            <span className="dp-blink">▍</span> streaming · polling every 3s
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
