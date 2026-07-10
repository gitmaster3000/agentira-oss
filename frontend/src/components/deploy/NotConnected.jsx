import React from 'react';
import { Zap, Rocket } from 'lucide-react';
import { C, MONO } from './theme';

export const PROVIDERS = [
    { id: 'railway', name: 'Railway', available: true },
    { id: 'gcp', name: 'Google Cloud', available: false },
    { id: 'docker', name: 'Docker', available: false },
];

function ProviderTile({ provider }) {
    const on = provider.available;
    return (
        <div
            style={{
                display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8,
                padding: '14px 10px', borderRadius: 11,
                background: on ? C.raised : '#131720',
                border: `1px solid ${on ? 'rgba(56,189,248,.3)' : C.borderSoft}`,
                opacity: on ? 1 : 0.62,
            }}
        >
            <span style={{ width: 32, height: 32, borderRadius: 9, background: C.bg, border: `1px solid ${C.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <ProviderMark id={provider.id} color={on ? C.textSoft : C.textDim} />
            </span>
            <div style={{ fontSize: 12.5, fontWeight: 600, color: on ? C.text : C.textMuted }}>{provider.name}</div>
            <span style={{
                fontSize: 9, fontWeight: 700, letterSpacing: '.06em',
                color: on ? C.info : C.textDim,
                background: on ? 'rgba(56,189,248,.14)' : 'rgba(118,131,144,.12)',
                borderRadius: 5, padding: '2px 8px',
            }}>{on ? 'AVAILABLE' : 'COMING'}</span>
        </div>
    );
}

// The three provider glyphs are hand-drawn in the design (Railway's asterisk,
// GCP's stacked planes, Docker's containers) — lucide has no stand-in.
export function ProviderMark({ id, color = C.textSoft, size = 17 }) {
    const p = { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: color, strokeWidth: 1.8 };
    if (id === 'gcp') return <svg {...p}><path d="M12 2 2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" /></svg>;
    if (id === 'docker') return <svg {...p}><path d="M3 9h4v4H3zM8 9h4v4H8zM13 9h4v4h-4zM8 4h4v4H8z" /><path d="M2 13h18a2 2 0 0 1-2 5H8a6 6 0 0 1-6-5z" /></svg>;
    return <svg {...p}><path d="M3 12h18M12 3v18M5.6 5.6l12.8 12.8M18.4 5.6 5.6 18.4" /></svg>;
}

/**
 * First thing most users see. One value prop, one CTA, providers shown plainly.
 */
export function NotConnected({ projectName, onConnect }) {
    return (
        <div style={{ padding: '32px 40px', display: 'flex', justifyContent: 'center' }}>
            <div style={{ width: '100%', maxWidth: 640, background: C.panel, border: `1px solid ${C.border}`, borderRadius: 14, overflow: 'hidden', boxShadow: '0 10px 30px rgba(0,0,0,.35)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '11px 16px', borderBottom: `1px solid ${C.border}` }}>
                    <Rocket className="w-4 h-4" style={{ color: C.info }} />
                    <span style={{ fontSize: 12.5, fontWeight: 600, color: C.text }}>Deploy</span>
                    <span style={{ fontSize: 11, color: C.textFaint, marginLeft: 'auto' }}>{projectName}</span>
                </div>

                <div style={{ padding: '34px 40px 30px', textAlign: 'center', background: 'radial-gradient(520px 220px at 50% -20%,rgba(56,189,248,.07),transparent)' }}>
                    <div style={{ width: 56, height: 56, borderRadius: 16, margin: '0 auto 18px', background: 'rgba(56,189,248,.10)', border: '1px solid rgba(56,189,248,.30)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <Rocket className="w-6 h-6" style={{ color: C.info }} strokeWidth={1.8} />
                    </div>
                    <h3 style={{ fontSize: 20, fontWeight: 700, margin: '0 0 8px', letterSpacing: '-.01em', color: C.text }}>Ship this project live</h3>
                    <p style={{ fontSize: 13, color: C.textDim, margin: '0 auto 22px', maxWidth: '46ch', lineHeight: 1.6 }}>
                        Connect a cloud provider once. After that, every push to <span style={{ fontFamily: MONO, color: C.textMuted }}>main</span> deploys
                        automatically and you get a live URL — plus one-click previews for any branch, right here in Agentira.
                    </p>
                    <button
                        onClick={onConnect}
                        style={{
                            display: 'inline-flex', alignItems: 'center', gap: 8, background: C.info, color: C.infoInk,
                            fontSize: 13, fontWeight: 600, padding: '10px 20px', borderRadius: 10, border: 'none',
                            cursor: 'pointer', fontFamily: 'inherit', boxShadow: '0 6px 18px rgba(56,189,248,.25)',
                        }}
                    >
                        <Zap className="w-4 h-4" strokeWidth={2.2} />
                        Connect a deployment provider
                    </button>
                    <div style={{ fontSize: 11, color: C.textFaint, marginTop: 12 }}>Takes about a minute · bring your own API key</div>
                </div>

                <div style={{ padding: '16px 22px 22px', borderTop: `1px solid ${C.borderSoft}` }}>
                    <div style={{ fontSize: 10.5, fontWeight: 600, letterSpacing: '.04em', color: C.textDim, textAlign: 'center', marginBottom: 12 }}>SUPPORTED PROVIDERS</div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 10 }}>
                        {PROVIDERS.map(p => <ProviderTile key={p.id} provider={p} />)}
                    </div>
                </div>
            </div>
        </div>
    );
}

/**
 * Edge state: provider connected, but main has never been deployed.
 */
export function NoDeployYet({ providerName, onDeployMain, busy }) {
    return (
        <div style={{ padding: '32px 40px', display: 'flex', justifyContent: 'center' }}>
            <div style={{ width: 360, background: C.bg, border: `1px solid ${C.border}`, borderRadius: 14, overflow: 'hidden' }}>
                <div style={{ padding: '11px 15px', borderBottom: `1px solid ${C.border}`, fontSize: 11, color: C.textDim }}>Connected · main never deployed</div>
                <div style={{ padding: '26px 20px', textAlign: 'center' }}>
                    <div style={{ width: 44, height: 44, borderRadius: 12, margin: '0 auto 14px', background: 'rgba(118,131,144,.1)', border: `1px dashed ${C.textFaint}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <Rocket className="w-5 h-5" style={{ color: C.textDim }} strokeWidth={1.8} />
                    </div>
                    <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 6, color: C.text }}>No deploy yet</div>
                    <div style={{ fontSize: 11.5, color: C.textDim, lineHeight: 1.55, marginBottom: 16 }}>
                        {providerName} is connected but <span style={{ fontFamily: MONO, color: C.textMuted }}>main</span> hasn't been
                        deployed. Push to <span style={{ fontFamily: MONO, color: C.textMuted }}>main</span>, or trigger the first one now.
                    </div>
                    <button
                        onClick={onDeployMain}
                        disabled={busy}
                        style={{
                            display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 12, fontWeight: 600,
                            color: C.infoInk, background: C.info, borderRadius: 9, padding: '8px 15px',
                            border: 'none', cursor: busy ? 'progress' : 'pointer', fontFamily: 'inherit', opacity: busy ? 0.7 : 1,
                        }}
                    >
                        <Zap className="w-3.5 h-3.5" strokeWidth={2.2} />
                        {busy ? 'Deploying…' : 'Deploy main now'}
                    </button>
                </div>
            </div>
        </div>
    );
}
