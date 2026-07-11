import React, { useState, memo } from 'react';
import { Check, CircleAlert } from 'lucide-react';
import { api } from '../../api';
import { C, MONO, timeAgo } from './theme';
import { ProviderMark } from './NotConnected';

function Row({ label, value }) {
    return (
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '8px 0', borderTop: `1px solid ${C.raised}`, fontSize: 11.5 }}>
            <span style={{ color: C.textDim }}>{label}</span>
            <span style={{ fontFamily: MONO, color: C.textMuted, textAlign: 'right' }}>{value}</span>
        </div>
    );
}

/**
 * Quiet, secondary. Never competes with the Live card.
 */
export const ProviderSettings = memo(function ProviderSettings({ projectId, connection, onChanged }) {
    const [busy, setBusy] = useState(false);
    const [confirmDisconnect, setConfirmDisconnect] = useState(false);
    const keyValid = connection.key_valid;

    const reverify = async () => {
        setBusy(true);
        try { await api.reverifyDeployProvider(projectId); await onChanged(); }
        finally { setBusy(false); }
    };

    const disconnect = async () => {
        setBusy(true);
        try { await api.disconnectDeployProvider(projectId); await onChanged(); }
        finally { setBusy(false); }
    };

    return (
        <div style={{ width: 360, flexShrink: 0, background: C.bg, border: `1px solid ${C.border}`, borderRadius: 12, overflow: 'hidden' }}>
            <div style={{ padding: '11px 15px', borderBottom: `1px solid ${C.border}`, fontSize: 11, color: C.textDim }}>Provider settings</div>
            <div style={{ padding: '16px 15px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
                    <span style={{ width: 32, height: 32, borderRadius: 9, background: C.raised, border: `1px solid ${C.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <ProviderMark id={connection.provider} size={16} />
                    </span>
                    <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 13, fontWeight: 600, color: C.text, textTransform: 'capitalize' }}>{connection.provider}</div>
                        <div style={{ fontSize: 10.5, color: C.textDim }}>connected {timeAgo(connection.connected_at)}</div>
                    </div>
                    {keyValid ? (
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 10, fontWeight: 600, color: C.good, background: 'rgba(46,204,113,.12)', border: '1px solid rgba(46,204,113,.35)', borderRadius: 999, padding: '3px 9px 3px 8px' }}>
                            <Check className="w-2.5 h-2.5" strokeWidth={2.6} />Key valid
                        </span>
                    ) : (
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 10, fontWeight: 600, color: C.bad, background: 'rgba(248,81,73,.12)', border: '1px solid rgba(248,81,73,.35)', borderRadius: 999, padding: '3px 9px 3px 8px' }}>
                            <CircleAlert className="w-2.5 h-2.5" strokeWidth={2.6} />Key invalid
                        </span>
                    )}
                </div>

                <Row label="Repo" value={connection.repo} />
                <Row label="Service" value={`${connection.service_name}${connection.service_region ? ` · ${connection.service_region}` : ''}`} />
                <Row label="Key last checked" value={timeAgo(connection.key_checked_at)} />

                {!keyValid && (
                    <div style={{ marginTop: 12, padding: '9px 11px', borderRadius: 9, background: 'rgba(248,81,73,.07)', border: '1px solid rgba(248,81,73,.32)', fontSize: 11, color: C.badText, lineHeight: 1.5 }}>
                        The stored key was rejected on last check. Deployments are paused until you re-verify or reconnect.
                    </div>
                )}

                <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
                    <button
                        onClick={reverify}
                        disabled={busy}
                        style={{ flex: 1, fontSize: 11.5, color: C.textMuted, padding: 8, border: `1px solid ${C.border}`, borderRadius: 8, background: C.raised, cursor: 'pointer', fontFamily: 'inherit' }}
                    >{busy ? 'Working…' : 'Re-verify key'}</button>
                    <button
                        onClick={() => (confirmDisconnect ? disconnect() : setConfirmDisconnect(true))}
                        disabled={busy}
                        style={{ flex: 1, fontSize: 11.5, color: C.bad, padding: 8, border: '1px solid rgba(248,81,73,.3)', borderRadius: 8, background: confirmDisconnect ? 'rgba(248,81,73,.1)' : 'transparent', cursor: 'pointer', fontFamily: 'inherit' }}
                    >{confirmDisconnect ? 'Confirm disconnect' : 'Disconnect'}</button>
                </div>
            </div>
        </div>
    );
});
