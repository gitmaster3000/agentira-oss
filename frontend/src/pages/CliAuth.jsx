import React, { useState, useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { api } from '../api';
import { Pencil, Terminal } from 'lucide-react';

export function CliAuth() {
    const { user, loading, loginWithOAuth } = useAuth();
    const [params] = useSearchParams();
    const [code, setCode] = useState(params.get('user_code') || '');
    const [status, setStatus] = useState('idle'); // idle | working | done | error
    const [error, setError] = useState('');
    const [authConfig, setAuthConfig] = useState({ google: false, github: false });
    const googleBtnRef = useRef(null);

    useEffect(() => {
        if (!user) api.getAuthConfig().then(setAuthConfig).catch(() => {});
    }, [user]);

    // Render the Google button inline when signed out — no page bounce, so the
    // ?user_code in the URL survives the sign-in.
    useEffect(() => {
        if (user || !authConfig.google || !window.google?.accounts?.id || !googleBtnRef.current) return;
        window.google.accounts.id.initialize({
            client_id: authConfig.google_client_id,
            callback: handleGoogleResponse,
        });
        window.google.accounts.id.renderButton(googleBtnRef.current, {
            theme: 'filled_black', size: 'large', width: 320, text: 'signin_with',
        });
    }, [authConfig.google, user]);

    const handleGoogleResponse = async (response) => {
        setError('');
        try {
            const data = await api.googleAuth(response.credential);
            await loginWithOAuth(data); // updates context → this page re-renders signed in
        } catch (err) {
            setError(err.message || 'Sign-in failed');
        }
    };

    const approve = async () => {
        setError(''); setStatus('working');
        try {
            await api.approveCliLogin(code.trim());
            setStatus('done');
        } catch (err) {
            setError(err.message || 'Failed to authorize'); setStatus('error');
        }
    };

    const Shell = ({ children }) => (
        <div className="h-full bg-bg-app flex flex-col items-center justify-center px-4">
            <div className="w-full max-w-sm space-y-6">
                <div className="flex items-center gap-2.5 justify-center">
                    <span className="w-9 h-9 rounded-md flex items-center justify-center" style={{ backgroundColor: 'rgba(201,184,255,0.1)' }}>
                        <Pencil className="w-5 h-5" style={{ color: 'var(--accent-primary)' }} />
                    </span>
                    <span className="text-title-sm font-semibold text-text-primary">AgentIRA</span>
                </div>
                <div className="card space-y-5">
                    <div className="text-center space-y-1">
                        <Terminal className="w-6 h-6 mx-auto" style={{ color: 'var(--accent-primary)' }} />
                        <h2 className="text-headline-sm text-text-primary">Authorize a daemon</h2>
                    </div>
                    {children}
                </div>
            </div>
        </div>
    );

    if (loading) return <Shell><p className="text-body-sm text-text-tertiary text-center">Loading…</p></Shell>;

    // Signed out → sign in right here (code stays in the URL).
    if (!user) {
        return (
            <Shell>
                <p className="text-body-sm text-text-tertiary text-center">
                    Sign in as an admin to connect your daemon.
                </p>
                {error && <div className="p-3 text-body-sm text-red-400 bg-red-900/20 border border-red-800 rounded-md">{error}</div>}
                {authConfig.google
                    ? <div ref={googleBtnRef} className="flex justify-center" />
                    : <p className="text-body-sm text-text-tertiary text-center">Google sign-in unavailable.</p>}
            </Shell>
        );
    }

    const isAdmin = user.role === 'admin' || user.role?.name === 'admin';

    return (
        <Shell>
            <p className="text-body-sm text-text-tertiary text-center">
                Connect a runtime daemon to <span className="text-text-secondary">{user.display_name || user.name}</span>’s workspace.
            </p>

            {!isAdmin && (
                <div className="p-3 text-body-sm text-amber-400 bg-amber-900/20 border border-amber-800 rounded-md">
                    Only admins can connect a daemon. Sign in with an admin account.
                </div>
            )}

            {status === 'done' ? (
                <div className="p-3 text-body-sm text-green-400 bg-green-900/20 border border-green-800 rounded-md text-center">
                    ✓ Daemon authorized. Return to your terminal.
                </div>
            ) : (
                <>
                    {error && <div className="p-3 text-body-sm text-red-400 bg-red-900/20 border border-red-800 rounded-md">{error}</div>}
                    <div>
                        <label className="text-label-md text-text-secondary mb-1 block">Device code</label>
                        <input value={code} onChange={(e) => setCode(e.target.value)}
                            className="input text-center" placeholder="paste the code from your terminal" autoFocus />
                    </div>
                    <button onClick={approve} disabled={!isAdmin || !code.trim() || status === 'working'}
                        className="btn btn-primary w-full justify-center text-body-md">
                        {status === 'working' ? 'Authorizing…' : 'Authorize daemon'}
                    </button>
                </>
            )}
        </Shell>
    );
}
