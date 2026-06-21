/**
 * AP-302: git access token (PAT) editor with a validity indicator.
 *
 * Shared by Project Settings (per-repo token) and Agent Settings (the
 * agent's personal token). The token value is write-only — the backend
 * never returns it, so we only ever show presence + cached validity +
 * when it was last checked.
 *
 * Props:
 *   hasToken    — bool: a token is stored
 *   valid       — bool|null: last probe result (null = never checked)
 *   checkedAt   — ISO string|null: when validity was last probed
 *   onSave      — async (token) => void : store/replace (or clear when '')
 *   onCheck     — async () => void : re-probe the stored token
 *   label, hint — copy
 */
import { useState } from 'react';
import { CheckCircle, XCircle, HelpCircle, RefreshCw } from 'lucide-react';

function relTime(iso) {
    if (!iso) return null;
    const secs = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
    if (secs < 60) return 'just now';
    if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
    if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
    return `${Math.floor(secs / 86400)}d ago`;
}

function ValidityBadge({ hasToken, valid }) {
    if (!hasToken) {
        return <span className="text-[11px] text-text-tertiary">no token</span>;
    }
    if (valid === true) {
        return (
            <span className="text-[11px] text-green-400 flex items-center gap-1">
                <CheckCircle className="w-3.5 h-3.5" /> valid
            </span>
        );
    }
    if (valid === false) {
        return (
            <span className="text-[11px] text-red-400 flex items-center gap-1">
                <XCircle className="w-3.5 h-3.5" /> invalid
            </span>
        );
    }
    return (
        <span className="text-[11px] text-text-tertiary flex items-center gap-1">
            <HelpCircle className="w-3.5 h-3.5" /> unchecked
        </span>
    );
}

export function GitTokenField({ hasToken, valid, checkedAt, onSave, onCheck,
                                label = 'Git access token',
                                hint = 'Personal access token so dispatched agents can clone/push private repos.' }) {
    const [value, setValue] = useState('');
    const [busy, setBusy] = useState('');
    const [err, setErr] = useState('');

    const run = async (kind, fn) => {
        setBusy(kind);
        setErr('');
        try {
            await fn();
            if (kind === 'save') setValue('');
        } catch (e) {
            setErr(e.message || String(e));
        } finally {
            setBusy('');
        }
    };

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between">
                <label className="text-xs font-medium text-text-secondary">{label}</label>
                <div className="flex items-center gap-2">
                    <ValidityBadge hasToken={hasToken} valid={valid} />
                    {hasToken && (
                        <button type="button" disabled={busy}
                            onClick={() => run('check', onCheck)}
                            className="btn btn-ghost p-1" title="Re-check validity now">
                            <RefreshCw className={`w-3.5 h-3.5 ${busy === 'check' ? 'animate-spin' : ''}`} />
                        </button>
                    )}
                </div>
            </div>
            <div className="flex items-center gap-2">
                <input type="password" className="input flex-1"
                    placeholder={hasToken ? '••••••••  (set to replace)' : 'ghp_…'}
                    value={value}
                    onChange={(e) => setValue(e.target.value)} />
                <button type="button" disabled={busy || !value.trim()}
                    onClick={() => run('save', () => onSave(value.trim()))}
                    className="btn btn-secondary">
                    {busy === 'save' ? 'Saving…' : 'Save'}
                </button>
                {hasToken && (
                    <button type="button" disabled={busy}
                        onClick={() => run('save', () => onSave(''))}
                        className="btn btn-ghost text-red-400">
                        Clear
                    </button>
                )}
            </div>
            <div className="flex items-center justify-between">
                <span className="text-[11px] text-text-tertiary">{hint}</span>
                {hasToken && checkedAt && (
                    <span className="text-[11px] text-text-tertiary">
                        checked {relTime(checkedAt)}
                    </span>
                )}
            </div>
            {err && <div className="text-[11px] text-red-400">{err}</div>}
        </div>
    );
}
