import React from 'react';
import { Clock, AlertTriangle, OctagonAlert, Power } from 'lucide-react';
import { C, STATUS } from './theme';

// State is encoded in form + colour, never colour alone: each status carries a
// distinct icon (or dot treatment) and a written label. Design: "Status pills".
//
// queued   hollow clock  — waiting for a build slot
// building blinking dot  — in progress, page is polling
// live     pulsing dot   — running & reachable
// failed   triangle      — never finished building
// crashed  octagon       — built, then died at runtime
// stopped  dashed power  — preview torn down on purpose
function Glyph({ status, color }) {
    if (status === 'live') {
        return (
            <span
                className="dp-lp"
                data-testid="pill-glyph-live"
                style={{ position: 'relative', display: 'inline-flex', width: 8, height: 8, borderRadius: '50%', background: color, color }}
            />
        );
    }
    if (status === 'building' || status === 'queued') {
        if (status === 'queued') return <Clock className="w-3 h-3" strokeWidth={2} />;
        return (
            <span style={{ position: 'relative', display: 'inline-flex', width: 8, height: 8, color }}>
                <span className="dp-blink" style={{ position: 'absolute', inset: 0, borderRadius: '50%', background: 'currentColor' }} />
            </span>
        );
    }
    if (status === 'failed') return <AlertTriangle className="w-3 h-3" strokeWidth={2.2} />;
    if (status === 'crashed') return <OctagonAlert className="w-3 h-3" strokeWidth={2.2} />;
    return <Power className="w-3 h-3" strokeWidth={2} />;
}

/**
 * @param {object} props
 * @param {'queued'|'building'|'live'|'failed'|'crashed'|'stopped'|'none'} props.status
 * @param {string} [props.detail] e.g. "2/4" — appended as "Building · 2/4"
 */
export function StatusPill({ status, detail }) {
    const s = STATUS[status] || STATUS.none;
    const label = detail ? `${s.label} · ${detail}` : s.label;
    return (
        <span
            role="status"
            aria-label={label}
            style={{
                display: 'inline-flex', alignItems: 'center', gap: 7,
                fontSize: 11.5, fontWeight: 600, color: s.color,
                background: s.tint,
                border: `1px ${s.dashed ? 'dashed' : 'solid'} ${s.border}`,
                borderRadius: 999, padding: '4px 11px 4px 9px', whiteSpace: 'nowrap',
            }}
        >
            <Glyph status={status} color={s.color} />
            {label}
        </span>
    );
}

// The compact form used inside the branch switcher rows: dot + uppercase label.
export function StatusDot({ status }) {
    const s = STATUS[status] || STATUS.none;
    return <span style={{ width: 8, height: 8, borderRadius: '50%', background: s.color, flexShrink: 0 }} />;
}

export function statusColor(status) {
    return (STATUS[status] || STATUS.none).color;
}

export { C };
