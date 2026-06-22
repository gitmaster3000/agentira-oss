import React, { useState } from 'react';
import { api } from '../api';
import { useAuth } from '../context/AuthContext';

// AP-306: when an admin sets/resets a user's password, the account is flagged
// must_change_password. This non-dismissable overlay forces the user to pick a
// new password before they can use the app. Rendered inside RequireAuth so it
// covers every authenticated route.
export function ForcePasswordChange() {
    const { user, updateUser } = useAuth();
    const [next, setNext] = useState('');
    const [confirm, setConfirm] = useState('');
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);

    if (!user?.must_change_password) return null;

    const submit = async (e) => {
        e.preventDefault();
        setError('');
        if (next.length < 8) { setError('Use at least 8 characters.'); return; }
        if (next !== confirm) { setError('Passwords do not match.'); return; }
        setBusy(true);
        try {
            await api.changeMyPassword(next);
            updateUser({ must_change_password: false });
        } catch (err) {
            setError(err.message || 'Could not change password');
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/70 backdrop-blur-sm px-4">
            <div className="card w-full max-w-sm space-y-5">
                <div className="space-y-1">
                    <h2 className="text-headline-sm text-text-primary">Set a new password</h2>
                    <p className="text-body-sm text-text-tertiary">
                        Your password was set by an admin. Choose a new one to continue.
                    </p>
                </div>
                {error && <div className="p-3 text-body-sm text-red-400 bg-red-900/20 border border-red-800 rounded-md">{error}</div>}
                <form onSubmit={submit} className="space-y-4">
                    <div>
                        <label className="text-label-md text-text-secondary mb-1 block">New password</label>
                        <input type="password" autoComplete="new-password" autoFocus required
                            value={next} onChange={(e) => setNext(e.target.value)} className="input" placeholder="At least 8 characters" />
                    </div>
                    <div>
                        <label className="text-label-md text-text-secondary mb-1 block">Confirm new password</label>
                        <input type="password" autoComplete="new-password" required
                            value={confirm} onChange={(e) => setConfirm(e.target.value)} className="input" placeholder="••••••••" />
                    </div>
                    <button type="submit" disabled={busy} className="btn btn-primary w-full justify-center text-body-md">
                        {busy ? 'Saving…' : 'Update password'}
                    </button>
                </form>
            </div>
        </div>
    );
}
