import React, { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { ROUTES } from '../routes';
import { Pencil } from 'lucide-react';

export function ResetPassword() {
    const [searchParams] = useSearchParams();
    const token = searchParams.get('token') || '';
    const [next, setNext] = useState('');
    const [confirm, setConfirm] = useState('');
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);
    const navigate = useNavigate();

    const submit = async (e) => {
        e.preventDefault();
        setError('');
        if (next.length < 6) { setError('Use at least 6 characters.'); return; }
        if (next !== confirm) { setError('Passwords do not match.'); return; }
        setBusy(true);
        try {
            await api.resetPasswordWithToken(token, next);
            navigate(ROUTES.LOGIN, { replace: true, state: { message: 'Password updated — sign in with your new password.' } });
        } catch (err) {
            setError(err.message || 'This reset link is invalid or has expired.');
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="h-full bg-bg-app flex flex-col items-center justify-center px-4 overflow-y-auto">
            <div className="w-full max-w-sm space-y-6">
                <Link to={ROUTES.WELCOME} className="flex items-center gap-2.5 justify-center mb-2">
                    <span className="w-9 h-9 rounded-md flex items-center justify-center" style={{ backgroundColor: 'rgba(201, 184, 255, 0.1)' }}>
                        <Pencil className="w-5 h-5" style={{ color: 'var(--accent-primary)' }} />
                    </span>
                    <span className="text-title-sm font-semibold text-text-primary">AgentIRA</span>
                </Link>
                <div className="card space-y-5">
                    <h2 className="text-headline-sm text-text-primary text-center">Choose a new password</h2>
                    {!token ? (
                        <p className="text-body-sm text-red-400 text-center">This reset link is missing its token. Request a new one.</p>
                    ) : (
                        <>
                            {error && <div className="p-3 text-body-sm text-red-400 bg-red-900/20 border border-red-800 rounded-md">{error}</div>}
                            <form onSubmit={submit} className="space-y-4">
                                <div>
                                    <label className="text-label-md text-text-secondary mb-1 block">New password</label>
                                    <input type="password" autoComplete="new-password" required autoFocus
                                        value={next} onChange={(e) => setNext(e.target.value)} className="input" placeholder="••••••••" />
                                </div>
                                <div>
                                    <label className="text-label-md text-text-secondary mb-1 block">Confirm password</label>
                                    <input type="password" autoComplete="new-password" required
                                        value={confirm} onChange={(e) => setConfirm(e.target.value)} className="input" placeholder="••••••••" />
                                </div>
                                <button type="submit" disabled={busy} className="btn btn-primary w-full justify-center text-body-md">
                                    {busy ? 'Saving…' : 'Update password'}
                                </button>
                            </form>
                        </>
                    )}
                    <p className="text-body-sm text-text-tertiary text-center">
                        <Link to={ROUTES.FORGOT_PASSWORD} className="font-medium" style={{ color: 'var(--accent-primary)' }}>Request a new link</Link>
                    </p>
                </div>
            </div>
        </div>
    );
}
