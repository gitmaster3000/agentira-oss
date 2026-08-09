import React, { useCallback, useEffect, useState } from 'react';
import { Check, X, Eye, EyeOff, ExternalLink, Github, CircleAlert, RefreshCw, Server, Database } from 'lucide-react';
import { api } from '../../api';
import { C, MONO } from './theme';
import { ProviderMark } from './NotConnected';

const KEY_HELP = {
    railway: 'https://railway.app/account/tokens',
};

function StepBar({ step }) {
    const seg = (i) => ({
        width: step === i ? 18 : 8, height: 4, borderRadius: 2,
        background: step === i ? C.info : step > i ? '#1c4a5c' : C.border,
    });
    return <div style={{ display: 'flex', gap: 4 }}>{[1, 2, 3].map(i => <span key={i} style={seg(i)} />)}</div>;
}

function Panel({ step, title, subtitle, children, footer }) {
    return (
        <div style={{ width: 460, background: C.panel, border: `1px solid ${C.border}`, borderRadius: 14, overflow: 'hidden', boxShadow: '0 18px 44px rgba(0,0,0,.55)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '11px 15px', borderBottom: `1px solid ${C.border}` }}>
                <span style={{ fontSize: 11, fontWeight: 700, color: C.info }}>Step {step}</span>
                <span style={{ fontSize: 11, color: C.textDim }}>{title}</span>
                <div style={{ flex: 1 }} />
                {subtitle || <StepBar step={step} />}
            </div>
            <div style={{ padding: '16px 15px' }}>{children}</div>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '12px 15px', borderTop: `1px solid ${C.border}` }}>{footer}</div>
        </div>
    );
}

const ghostBtn = { fontSize: 12, color: C.textDim, padding: '7px 13px', background: 'transparent', border: 'none', cursor: 'pointer', fontFamily: 'inherit' };
const primaryBtn = (bg = C.info, ink = C.infoInk) => ({ fontSize: 12, fontWeight: 600, color: ink, background: bg, padding: '7px 15px', borderRadius: 8, border: 'none', cursor: 'pointer', fontFamily: 'inherit' });

// ── Step 1 — paste the key, probe it once, never echo it back ────────────────
function KeyStep({ provider, apiKey, setApiKey, verify, state, result, error, onCancel, onNext }) {
    const [shown, setShown] = useState(false);
    const checking = state === 'checking';
    const valid = state === 'valid';
    const invalid = state === 'invalid';

    return (
        <Panel
            step={1}
            title={checking ? 'Verifying' : 'API key'}
            subtitle={invalid ? <span style={{ fontSize: 10, color: C.bad }}>verification failed</span> : null}
            footer={<>
                <button style={ghostBtn} onClick={onCancel}>Cancel</button>
                {valid
                    ? <button style={primaryBtn()} onClick={onNext}>Continue</button>
                    : <button style={{ ...primaryBtn(), opacity: !apiKey || checking ? 0.6 : 1 }} disabled={!apiKey || checking} onClick={verify}>
                        {checking ? 'Checking…' : invalid ? 'Try again' : 'Verify key'}
                    </button>}
            </>}
        >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 13 }}>
                <span style={{ width: 26, height: 26, borderRadius: 8, background: C.bg, border: `1px solid ${C.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <ProviderMark id={provider} size={14} />
                </span>
                <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: C.text, textTransform: 'capitalize' }}>{provider}</div>
                    <a href={KEY_HELP[provider]} target="_blank" rel="noreferrer" style={{ fontSize: 10.5, color: C.info, textDecoration: 'none' }}>Where do I find my key? ↗</a>
                </div>
            </div>

            <label htmlFor="deploy-api-key" style={{ display: 'block', fontSize: 10.5, fontWeight: 600, letterSpacing: '.04em', color: C.textDim, marginBottom: 6 }}>API KEY</label>
            <div style={{
                display: 'flex', alignItems: 'center', gap: 8, background: C.raised, borderRadius: 9, padding: '9px 11px',
                border: `1px solid ${invalid ? 'rgba(248,81,73,.45)' : checking ? 'rgba(56,189,248,.4)' : C.border}`,
            }}>
                <input
                    id="deploy-api-key"
                    type={shown ? 'text' : 'password'}
                    value={apiKey}
                    onChange={e => setApiKey(e.target.value)}
                    placeholder="Paste your API key"
                    autoComplete="off"
                    style={{ flex: 1, background: 'transparent', border: 'none', outline: 'none', color: C.textSoft, fontSize: 12.5, fontFamily: MONO }}
                />
                {checking
                    ? <RefreshCw className="w-3.5 h-3.5 dp-blink" style={{ color: C.info }} />
                    : invalid
                        ? <X className="w-3.5 h-3.5" style={{ color: C.bad }} />
                        : <button aria-label={shown ? 'Hide key' : 'Show key'} onClick={() => setShown(s => !s)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: C.textDim, padding: 0, display: 'flex' }}>
                            {shown ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                        </button>}
            </div>

            {state === 'idle' && (
                <div style={{ fontSize: 10.5, color: C.textFaint, marginTop: 8, lineHeight: 1.5 }}>
                    Stored encrypted. We probe it once to verify, then never show it again.
                </div>
            )}

            {checking && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12, padding: '9px 11px', borderRadius: 9, background: 'rgba(56,189,248,.08)', border: '1px solid rgba(56,189,248,.25)' }}>
                    <span className="dp-blink" style={{ width: 7, height: 7, borderRadius: '50%', background: C.info }} />
                    <span style={{ fontSize: 11.5, color: C.infoText, textTransform: 'capitalize' }}>Checking with {provider}…</span>
                </div>
            )}

            {valid && result && (
                <div style={{ marginTop: 14, padding: 11, borderRadius: 10, background: 'rgba(46,204,113,.07)', border: '1px solid rgba(46,204,113,.3)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <Check className="w-4 h-4" style={{ color: C.good }} strokeWidth={2.4} />
                        <span style={{ fontSize: 12, fontWeight: 600, color: C.good }}>Key valid</span>
                    </div>
                    <div style={{ fontSize: 10.5, color: C.textDim, marginTop: 5 }}>
                        Account: <b style={{ fontFamily: MONO, color: C.textMuted, fontWeight: 600 }}>{result.account}</b> · {result.services?.length ?? 0} services
                    </div>
                </div>
            )}

            {invalid && (
                <div style={{ marginTop: 12, padding: '11px 12px', borderRadius: 10, background: 'rgba(248,81,73,.07)', border: '1px solid rgba(248,81,73,.32)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                        <CircleAlert className="w-3.5 h-3.5" style={{ color: C.bad }} strokeWidth={2.2} />
                        <span style={{ fontSize: 12, fontWeight: 600, color: C.bad }}>{error?.headline || 'Key rejected'}</span>
                    </div>
                    <div style={{ fontSize: 11, color: C.badText, lineHeight: 1.5 }}>
                        {error?.detail || 'It may be expired or revoked. Generate a fresh token and paste it again.'}{' '}
                        <a href={KEY_HELP[provider]} target="_blank" rel="noreferrer" style={{ color: C.infoText, textDecoration: 'none' }}>Open tokens ↗</a>
                    </div>
                </div>
            )}
        </Panel>
    );
}

// ── Step 2 — the one-time GitHub App install; can't be skipped ───────────────
function RepoStep({ provider, access, onBack, onNext, onRecheck }) {
    const granted = !!access?.granted;
    return (
        <Panel
            step={2}
            title="Repo access"
            footer={<>
                <button style={ghostBtn} onClick={onBack}>Back</button>
                {granted
                    ? <button style={primaryBtn()} onClick={onNext}>Continue</button>
                    : <button style={{ ...primaryBtn(C.raised, C.textDim), border: `1px solid ${C.border}` }} onClick={onRecheck}>Waiting…</button>}
            </>}
        >
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4, color: C.text }}>Grant access to the repo</div>
            <div style={{ fontSize: 11.5, color: C.textDim, marginBottom: 14, textTransform: 'none' }}>
                A one-time GitHub App install so <span style={{ textTransform: 'capitalize' }}>{provider}</span> can read{' '}
                <span style={{ fontFamily: MONO, color: C.textMuted }}>{access?.repo || 'this repo'}</span> and build on push.
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '11px 12px', borderRadius: 10, background: C.raised, border: `1px solid ${C.border}`, marginBottom: 12 }}>
                <Github className="w-4 h-4" style={{ color: C.textSoft }} />
                <span style={{ flex: 1, fontFamily: MONO, fontSize: 12, color: C.textSoft }}>{access?.repo || '—'}</span>
                {granted
                    ? <span style={{ fontSize: 9, fontWeight: 700, color: C.good, background: 'rgba(46,204,113,.12)', border: '1px solid rgba(46,204,113,.3)', borderRadius: 5, padding: '2px 7px' }}>GRANTED</span>
                    : <span style={{ fontSize: 9, fontWeight: 700, color: C.warn, background: 'rgba(255,152,0,.12)', border: '1px solid rgba(255,152,0,.3)', borderRadius: 5, padding: '2px 7px' }}>NEEDS ACCESS</span>}
            </div>

            {!granted && (
                <>
                    <a
                        href={access?.install_url || '#'}
                        target="_blank"
                        rel="noreferrer"
                        style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, padding: 11, borderRadius: 10, background: C.bg, border: `1px solid ${C.border}`, fontSize: 12, fontWeight: 600, color: C.textSoft, textDecoration: 'none' }}
                    >
                        <ExternalLink className="w-3.5 h-3.5" />
                        Grant on GitHub
                    </a>
                    <div style={{ fontSize: 10, color: C.textFaint, marginTop: 9, textAlign: 'center', lineHeight: 1.5 }}>
                        Opens GitHub in a new tab · required, can't skip
                    </div>
                </>
            )}
        </Panel>
    );
}

// ── Step 3 — which service hosts main ───────────────────────────────────────
function ServiceStep({ services, selected, onSelect, onBack, onConnect, busy }) {
    return (
        <Panel
            step={3}
            title="Service"
            footer={<>
                <button style={ghostBtn} onClick={onBack}>Back</button>
                <button
                    style={{ ...primaryBtn(C.teal, C.bg), opacity: !selected || busy ? 0.6 : 1 }}
                    disabled={!selected || busy}
                    onClick={onConnect}
                >{busy ? 'Connecting…' : 'Connect'}</button>
            </>}
        >
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4, color: C.text }}>
                Which service deploys <span style={{ fontFamily: MONO }}>main</span>?
            </div>
            <div style={{ fontSize: 11.5, color: C.textDim, marginBottom: 14 }}>Pick the service that hosts this app.</div>

            {services.map(s => {
                const active = selected === s.id;
                const Icon = s.deployable ? Server : Database;
                return (
                    <button
                        key={s.id}
                        onClick={() => s.deployable && onSelect(s.id)}
                        disabled={!s.deployable}
                        aria-pressed={active}
                        style={{
                            width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 10,
                            padding: '11px 12px', borderRadius: 10, marginBottom: 8, fontFamily: 'inherit',
                            background: C.raised, cursor: s.deployable ? 'pointer' : 'not-allowed',
                            border: `1px solid ${active ? 'rgba(128,203,196,.4)' : C.border}`,
                        }}
                    >
                        <span style={{ width: 28, height: 28, borderRadius: 8, background: s.deployable ? 'rgba(128,203,196,.14)' : 'rgba(118,131,144,.12)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                            <Icon className="w-3.5 h-3.5" style={{ color: s.deployable ? C.teal : C.textDim }} />
                        </span>
                        <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontSize: 12.5, fontWeight: 600, color: s.deployable ? C.textSoft : C.textMuted }}>{s.name}</div>
                            <div style={{ fontSize: 10, color: C.textDim }}>
                                {s.type}{s.region ? ` · ${s.region}` : ''}{s.deployable ? '' : ' · not deployable'}
                            </div>
                        </div>
                        {active && (
                            <span style={{ width: 16, height: 16, borderRadius: '50%', background: C.teal, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                <Check className="w-2.5 h-2.5" style={{ color: C.bg }} strokeWidth={3.5} />
                            </span>
                        )}
                    </button>
                );
            })}
        </Panel>
    );
}

/**
 * Paste key → verify → grant repo → pick service → connect. Asked once.
 * `onConnected` fires with the fresh connection so the page can drop straight
 * into the Deploy home while the first build runs.
 */
export function ConnectWizard({ projectId, provider = 'railway', onClose, onConnected }) {
    const [step, setStep] = useState(1);
    const [apiKey, setApiKey] = useState('');
    const [keyState, setKeyState] = useState('idle'); // idle | checking | valid | invalid
    const [verifyResult, setVerifyResult] = useState(null);
    const [keyError, setKeyError] = useState(null);
    const [access, setAccess] = useState(null);
    const [serviceId, setServiceId] = useState(null);
    const [connecting, setConnecting] = useState(false);
    const [connectError, setConnectError] = useState(null);

    const verify = useCallback(async () => {
        setKeyState('checking');
        setKeyError(null);
        try {
            const res = await api.verifyDeployKey(projectId, provider, apiKey);
            if (res.valid) {
                setVerifyResult(res);
                setKeyState('valid');
            } else {
                setKeyError(res.error || null);
                setKeyState('invalid');
            }
        } catch (err) {
            setKeyError({ headline: 'Verification failed', detail: err.message });
            setKeyState('invalid');
        }
    }, [projectId, provider, apiKey]);

    const loadAccess = useCallback(async () => {
        try {
            setAccess(await api.getDeployRepoAccess(projectId, provider));
        } catch (err) {
            setAccess({ granted: false, repo: null, install_url: null, error: err.message });
        }
    }, [projectId, provider]);

    // While on the grant step, re-check every 3s — the user is in another tab.
    useEffect(() => {
        if (step !== 2) return undefined;
        loadAccess();
        if (access?.granted) return undefined;
        const t = setInterval(loadAccess, 3000);
        return () => clearInterval(t);
    }, [step, loadAccess, access?.granted]);

    const connect = async () => {
        setConnecting(true);
        setConnectError(null);
        try {
            const conn = await api.connectDeployProvider(projectId, {
                provider, api_key: apiKey, repo: access?.repo, service_id: serviceId,
            });
            onConnected(conn);
        } catch (err) {
            setConnectError(err.message);
            setConnecting(false);
        }
    };

    return (
        <div
            className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center"
            onClick={e => { if (e.target === e.currentTarget) onClose(); }}
        >
            <div role="dialog" aria-label="Connect a deployment provider">
                {step === 1 && (
                    <KeyStep
                        provider={provider} apiKey={apiKey} setApiKey={k => { setApiKey(k); setKeyState('idle'); }}
                        verify={verify} state={keyState} result={verifyResult} error={keyError}
                        onCancel={onClose} onNext={() => setStep(2)}
                    />
                )}
                {step === 2 && (
                    <RepoStep
                        provider={provider} access={access}
                        onBack={() => setStep(1)} onNext={() => setStep(3)} onRecheck={loadAccess}
                    />
                )}
                {step === 3 && (
                    <ServiceStep
                        services={verifyResult?.services || []} selected={serviceId} onSelect={setServiceId}
                        onBack={() => setStep(2)} onConnect={connect} busy={connecting}
                    />
                )}
                {connectError && (
                    <div style={{ marginTop: 10, fontSize: 11.5, color: C.bad, textAlign: 'center' }}>{connectError}</div>
                )}
            </div>
        </div>
    );
}
