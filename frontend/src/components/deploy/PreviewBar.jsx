import React, { useEffect, useRef, useState, memo } from 'react';
import { ChevronDown, Copy, Check, RefreshCw, ExternalLink, Plus, Pin } from 'lucide-react';
import { C, MONO, STATUS, statusOf, timeAgo } from './theme';
import { StatusDot } from './StatusPill';

function statusLabel(entry) {
    const s = statusOf(entry.deployment);
    if (s === 'building' && entry.deployment?.step && entry.deployment?.total_steps) {
        return `BUILDING · ${entry.deployment.step}/${entry.deployment.total_steps}`;
    }
    return STATUS[s].label.toUpperCase();
}

function BranchMenu({ entries, selectedBranch, onSelect, onDeployNew, onClose }) {
    const ref = useRef(null);
    useEffect(() => {
        function handler(e) { if (ref.current && !ref.current.contains(e.target)) onClose(); }
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, [onClose]);

    return (
        <div ref={ref} role="menu" aria-label="Switch preview" style={{ position: 'absolute', top: 'calc(100% + 8px)', left: 0, width: 400, background: C.panel, border: `1px solid ${C.border}`, borderRadius: 12, boxShadow: '0 18px 44px rgba(0,0,0,.55)', zIndex: 60, overflow: 'hidden' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '11px 14px', borderBottom: `1px solid ${C.borderSoft}` }}>
                <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.1em', color: '#aeb6c0' }}>SWITCH PREVIEW</span>
                <div style={{ flex: 1 }} />
                <span style={{ fontSize: 10, color: C.textFaint }}>Spin up a preview to test before merge</span>
            </div>
            <div style={{ maxHeight: 330, overflowY: 'auto', padding: 6 }}>
                {entries.map(entry => {
                    const active = entry.branch === selectedBranch;
                    return (
                        <button
                            key={entry.branch}
                            role="menuitem"
                            onClick={() => onSelect(entry.branch)}
                            style={{
                                width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 10,
                                padding: '9px 11px', borderRadius: 9, cursor: 'pointer', border: 'none', fontFamily: 'inherit',
                                background: active ? 'rgba(56,189,248,.10)' : 'transparent',
                            }}
                        >
                            <StatusDot status={statusOf(entry.deployment)} />
                            <div style={{ minWidth: 0, flex: 1 }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                    <span style={{ fontFamily: MONO, fontSize: 12, fontWeight: 600, color: C.textSoft }}>{entry.branch}</span>
                                    <span style={{ fontSize: 9, fontWeight: 700, color: STATUS[statusOf(entry.deployment)].color }}>{statusLabel(entry)}</span>
                                </div>
                                <div style={{ fontSize: 10, color: C.textDim, marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{entry.commit_message}</div>
                            </div>
                            <span style={{ fontSize: 9.5, color: C.textFaint, flexShrink: 0 }}>{timeAgo(entry.deployment?.updated_at || entry.committed_at)}</span>
                        </button>
                    );
                })}
            </div>
            <div style={{ borderTop: `1px solid ${C.borderSoft}`, padding: 8 }}>
                <button
                    onClick={onDeployNew}
                    style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7, padding: 8, borderRadius: 8, background: C.raised, border: `1px solid ${C.border}`, fontSize: 11.5, fontWeight: 600, color: C.textSoft, cursor: 'pointer', fontFamily: 'inherit' }}
                >
                    <Plus className="w-3.5 h-3.5" style={{ color: C.info }} strokeWidth={2.2} />
                    Deploy a new branch preview
                </button>
            </div>
        </div>
    );
}

const chip = { display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, color: C.textMuted, padding: '5px 10px', border: `1px solid ${C.border}`, borderRadius: 7, flexShrink: 0, background: 'transparent', cursor: 'pointer', fontFamily: 'inherit' };

/**
 * The header bar of the Deploy tab: branch selector, URL, actions.
 * Arrow hides the bar; pin toggles sticky.
 */
export const PreviewBar = memo(function PreviewBar({
    entries, selectedBranch, onSelectBranch, onDeployNew,
    onRedeploy, pinned, onTogglePin, busy,
}) {
    const [menuOpen, setMenuOpen] = useState(false);
    const [copied, setCopied] = useState(false);
    const current = entries.find(e => e.branch === selectedBranch) || entries[0];
    if (!current) return null;

    const status = statusOf(current.deployment);
    const url = current.deployment?.url;
    const dot = STATUS[status].color;

    const copy = async () => {
        if (!url) return;
        await navigator.clipboard.writeText(url);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
    };

    return (
        <div style={{
            position: pinned ? 'sticky' : 'static', top: 0, zIndex: 20,
            display: 'flex', alignItems: 'center', gap: 10, padding: '12px 40px',
            background: 'rgba(20,22,27,.86)', backdropFilter: 'blur(10px)', WebkitBackdropFilter: 'blur(10px)',
            borderBottom: `1px solid ${C.border}`,
        }}>
            <span style={{ fontSize: 12, fontWeight: 800, letterSpacing: '.1em', color: '#fff', flexShrink: 0 }}>PREVIEW</span>

            <div style={{ position: 'relative', flexShrink: 0 }}>
                <button
                    onClick={() => setMenuOpen(o => !o)}
                    aria-expanded={menuOpen}
                    aria-haspopup="menu"
                    aria-label={`Switch preview — showing ${current.branch}`}
                    style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '5px 10px', borderRadius: 8, background: C.raised, border: `1px solid ${C.borderStrong}`, cursor: 'pointer', fontFamily: 'inherit' }}
                >
                    <span style={{ width: 8, height: 8, borderRadius: '50%', background: dot, flexShrink: 0 }} />
                    <span style={{ fontFamily: MONO, fontSize: 13, fontWeight: 600, color: C.text }}>{current.branch}</span>
                    <span style={{ fontSize: 9.5, fontWeight: 700, color: dot }}>{statusLabel(current)}</span>
                    <span style={{ width: 1, height: 14, background: C.borderStrong, margin: '0 1px' }} />
                    <ChevronDown className="w-3.5 h-3.5" style={{ color: '#aeb6c0', transform: menuOpen ? 'rotate(180deg)' : 'none', transition: 'transform .15s' }} />
                </button>
                {menuOpen && (
                    <BranchMenu
                        entries={entries}
                        selectedBranch={current.branch}
                        onSelect={(b) => { onSelectBranch(b); setMenuOpen(false); }}
                        onDeployNew={() => { setMenuOpen(false); onDeployNew(); }}
                        onClose={() => setMenuOpen(false)}
                    />
                )}
            </div>

            <span style={{ width: 1, height: 16, background: C.border, flexShrink: 0 }} />

            {url ? (
                <a href={url} target="_blank" rel="noreferrer" style={{ flex: 1, fontFamily: MONO, fontSize: 13, color: C.infoText, textDecoration: 'none', fontWeight: 600, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{url}</a>
            ) : (
                <span style={{ flex: 1, fontFamily: MONO, fontSize: 13, color: C.textFaint, minWidth: 0 }}>
                    {status === 'building' || status === 'queued' ? 'building…' : '—'}
                </span>
            )}

            <button style={chip} onClick={copy} disabled={!url} title="Copy URL">
                {copied ? <Check className="w-3 h-3" style={{ color: C.good }} /> : <Copy className="w-3 h-3" />}
                {copied ? 'Copied' : 'Copy'}
            </button>
            <button style={chip} onClick={onRedeploy} disabled={busy} title="Redeploy this branch">
                <RefreshCw className={`w-3 h-3 ${busy ? 'dp-blink' : ''}`} />
                Redeploy
            </button>
            <a
                href={url || '#'}
                target="_blank"
                rel="noreferrer"
                aria-disabled={!url}
                style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11.5, fontWeight: 600, color: C.infoInk, background: C.info, padding: '6px 12px', borderRadius: 8, flexShrink: 0, textDecoration: 'none', opacity: url ? 1 : 0.4, pointerEvents: url ? 'auto' : 'none' }}
            >
                <ExternalLink className="w-3 h-3" strokeWidth={2.2} />
                Open
            </a>

            <span style={{ width: 1, height: 18, background: C.border, flexShrink: 0, margin: '0 2px' }} />

            <button
                onClick={onTogglePin}
                title="Pin header"
                aria-pressed={pinned}
                style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 28, height: 28, borderRadius: 7, cursor: 'pointer', flexShrink: 0, color: pinned ? C.info : C.textDim, background: pinned ? 'rgba(56,189,248,.12)' : 'transparent', border: `1px solid ${pinned ? 'rgba(56,189,248,.38)' : C.border}` }}
            >
                <Pin className="w-3.5 h-3.5" fill={pinned ? C.info : 'none'} />
            </button>
        </div>
    );
});
