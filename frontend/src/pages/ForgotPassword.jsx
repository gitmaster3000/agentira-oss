import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { ROUTES } from '../routes';
import { Pencil } from 'lucide-react';

export function ForgotPassword() {
    const [email, setEmail] = useState('');
    const [sent, setSent] = useState(false);
    const [busy, setBusy] = useState(false);
    const [devNote, setDevNote] = useState('');
    const navigate = useNavigate();

    const submit = async (e) => {
        e.preventDefault();
        setBusy(true);
        // Always succeeds server-side (no account enumeration); show the same
        // confirmation regardless. Dev mode (AGENTIRA_ENV=dev) returns the link
        // itself — skip the email and go straight to it.
        let res = null;
        try { res = await api.forgotPassword(email); } catch { /* ignore */ }
        setBusy(false);
        if (res?.reset_url) { navigate(res.reset_url); return; }
        setDevNote(res?.dev_note || '');
        setSent(true);
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
                    <h2 className="text-headline-sm text-text-primary text-center">Reset your password</h2>
                    {sent && devNote ? (
                        <p className="text-body-sm text-text-tertiary text-center">
                            Dev mode: {devNote} (<span className="text-text-secondary">{email}</span>).
                        </p>
                    ) : sent ? (
                        <p className="text-body-sm text-text-tertiary text-center">
                            If an account exists for <span className="text-text-secondary">{email}</span>, a reset link is on its way. Check your inbox.
                        </p>
                    ) : (
                        <form onSubmit={submit} className="space-y-4">
                            <p className="text-body-sm text-text-tertiary text-center">
                                Enter your email and we'll send you a link to set a new password.
                            </p>
                            <div>
                                <label className="text-label-md text-text-secondary mb-1 block">Email</label>
                                <input type="email" autoComplete="email" required autoFocus
                                    value={email} onChange={(e) => setEmail(e.target.value)}
                                    className="input" placeholder="you@example.com" />
                            </div>
                            <button type="submit" disabled={busy} className="btn btn-primary w-full justify-center text-body-md">
                                {busy ? 'Sending…' : 'Send reset link'}
                            </button>
                        </form>
                    )}
                    <p className="text-body-sm text-text-tertiary text-center">
                        <Link to={ROUTES.LOGIN} className="font-medium" style={{ color: 'var(--accent-primary)' }}>Back to sign in</Link>
                    </p>
                </div>
            </div>
        </div>
    );
}
