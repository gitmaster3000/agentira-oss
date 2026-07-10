import React, { useState } from 'react';
import { ExternalLink, Play, RefreshCw, Square, ScrollText } from 'lucide-react';
import { C, MONO, statusOf, timeAgo } from './theme';
import { StatusPill } from './StatusPill';

const rowBtn = { display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, fontWeight: 600, padding: '5px 9px', borderRadius: 7, cursor: 'pointer', fontFamily: 'inherit', background: 'transparent', border: `1px solid ${C.border}`, color: C.textMuted, flexShrink: 0 };

// Many branches are possible, so this list stays scannable: one row each,
// primary action on the right, everything else quiet.
const PAGE = 8;

function Row({ entry, onPreview, onRedeploy, onStop, onOpenLogs, busyBranch }) {
    const d = entry.deployment;
    const status = statusOf(d);
    const busy = busyBranch === entry.branch;
    const detail = status === 'building' && d?.step ? `${d.step}/${d.total_steps}` : undefined;

    return (
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '11px 14px', borderTop: `1px solid ${C.borderSoft}` }}>
            <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
                    <span style={{ fontFamily: MONO, fontSize: 12.5, fontWeight: 600, color: C.textSoft }}>{entry.branch}</span>
                    {entry.is_main && <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: '.06em', color: C.teal, background: 'rgba(128,203,196,.12)', borderRadius: 5, padding: '2px 6px' }}>MAIN</span>}
                </div>
                <div style={{ fontSize: 10.5, color: C.textDim, marginTop: 3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    <span style={{ fontFamily: MONO }}>{(entry.commit_sha || '').slice(0, 7)}</span>
                    {entry.commit_message ? ` · ${entry.commit_message}` : ''} · {timeAgo(d?.updated_at || entry.committed_at)}
                </div>
            </div>

            <StatusPill status={status} detail={detail} />

            {d && (
                <button style={rowBtn} onClick={() => onOpenLogs(d.id)} title="View logs">
                    <ScrollText className="w-3 h-3" />
                    Logs
                </button>
            )}

            {status === 'live' && d?.url && (
                <a style={{ ...rowBtn, textDecoration: 'none' }} href={d.url} target="_blank" rel="noreferrer" title="Open preview">
                    <ExternalLink className="w-3 h-3" />
                    Open
                </a>
            )}

            {status === 'live' && !entry.is_main && (
                <button style={{ ...rowBtn, color: C.bad, borderColor: 'rgba(248,81,73,.3)' }} onClick={() => onStop(d.id)} disabled={busy} title="Tear down preview">
                    <Square className="w-3 h-3" />
                    Stop
                </button>
            )}

            {(status === 'failed' || status === 'crashed') && (
                <button style={rowBtn} onClick={() => onRedeploy(entry)} disabled={busy} title="Redeploy">
                    <RefreshCw className={`w-3 h-3 ${busy ? 'dp-blink' : ''}`} />
                    Retry
                </button>
            )}

            {(status === 'none' || status === 'stopped') && (
                <button
                    style={{ ...rowBtn, color: C.infoInk, background: C.info, border: 'none', opacity: busy ? 0.7 : 1 }}
                    onClick={() => onPreview(entry)}
                    disabled={busy}
                >
                    <Play className="w-3 h-3" strokeWidth={2.4} />
                    {busy ? 'Starting…' : status === 'stopped' ? 'Redeploy preview' : 'Preview this branch'}
                </button>
            )}
        </div>
    );
}

export function BranchList({ entries, onPreview, onRedeploy, onStop, onOpenLogs, busyBranch }) {
    const [expanded, setExpanded] = useState(false);
    const rows = expanded ? entries : entries.slice(0, PAGE);
    const hidden = entries.length - rows.length;

    return (
        <div style={{ borderRadius: 12, border: `1px solid ${C.border}`, background: C.panel, overflow: 'hidden' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '11px 14px' }}>
                <h2 style={{ margin: 0, fontSize: 12.5, fontWeight: 600, color: C.text }}>Branch deployments</h2>
                <span style={{ fontSize: 11, color: C.textFaint }}>· preview any branch before it merges</span>
                <div style={{ flex: 1 }} />
                <span style={{ fontSize: 11, color: C.textDim }}>{entries.length}</span>
            </div>

            {entries.length === 0 && (
                <div style={{ padding: '22px 14px', textAlign: 'center', fontSize: 11.5, color: C.textDim, borderTop: `1px solid ${C.borderSoft}` }}>
                    No active branches.
                </div>
            )}

            {rows.map(entry => (
                <Row
                    key={entry.branch}
                    entry={entry}
                    onPreview={onPreview}
                    onRedeploy={onRedeploy}
                    onStop={onStop}
                    onOpenLogs={onOpenLogs}
                    busyBranch={busyBranch}
                />
            ))}

            {hidden > 0 && (
                <button
                    onClick={() => setExpanded(true)}
                    style={{ width: '100%', padding: '10px', borderTop: `1px solid ${C.borderSoft}`, background: 'transparent', border: 'none', color: C.textMuted, fontSize: 11.5, cursor: 'pointer', fontFamily: 'inherit' }}
                >
                    Show {hidden} more {hidden === 1 ? 'branch' : 'branches'}
                </button>
            )}
        </div>
    );
}
