import React, { useState, useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { api } from '../api';
import { Pencil, Terminal } from 'lucide-react';

// Module-level on purpose: defined inside CliAuth it became a new component
// type every render, so React remounted the form and inputs lost focus per keystroke.
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

export function CliAuth() {
    const { user, loading, loginWithOAuth, login, logout } = useAuth();
    const [params] = useSearchParams();
    const [code, setCode] = useState(params.get('user_code') || '');
    const [status, setStatus] = useState('idle'); // idle | working | done | error
    const [error, setError] = useState('');
    const [authConfig, setAuthConfig] = useState({ google: false, github: false, dev: false });
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const googleBtnRef = useRef(null);

    const handlePasswordLogin = async (e) => {
        e.preventDefault();
        setError('');
        try {
            await login(username, password); // updates context → re-renders signed in
        } catch (err) {
            setError('Invalid username or password');
        }
    };

    useEffect(() => {
        api.getAuthConfig().then(setAuthConfig).catch(() => {});
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

    // Dev mode: signed-in admin + code in the URL → approve without the extra click.
    useEffect(() => {
        const admin = user && (user.role === 'admin' || user.role?.name === 'admin');
        if (authConfig.dev && admin && code.trim() && status === 'idle') approve();
    }, [authConfig.dev, user]);

    if (loading) return <Shell><p className="text-body-sm text-text-tertiary text-center">Loading…</p></Shell>;

    // Signed out → sign in right here (code stays in the URL).
    if (!user) {
        return (
            <Shell>
                <p className="text-body-sm text-text-tertiary text-center">
                    Sign in as an admin to connect your daemon.
                </p>
                {error && <div className="p-3 text-body-sm text-red-400 bg-red-900/20 border border-red-800 rounded-md">{error}</div>}

                {authConfig.google && <div ref={googleBtnRef} className="flex justify-center" />}

                {authConfig.google && (
                    <div className="relative">
                        <div className="absolute inset-0 flex items-center"><div className="w-full border-t" style={{ borderColor: 'var(--border-subtle)' }} /></div>
                        <div className="relative flex justify-center text-label-sm"><span className="px-3 text-text-tertiary" style={{ backgroundColor: 'var(--bg-card)' }}>or</span></div>
                    </div>
                )}

                <form onSubmit={handlePasswordLogin} className="space-y-3">
                    <input value={username} onChange={(e) => setUsername(e.target.value)}
                        className="input" placeholder="Username or email" autoComplete="username" autoFocus />
                    <input value={password} onChange={(e) => setPassword(e.target.value)}
                        type="password" className="input" placeholder="Password" autoComplete="current-password" />
                    <button type="submit" className="btn btn-primary w-full justify-center text-body-md">Sign in</button>
                </form>
            </Shell>
        );
    }

    const isAdmin = user.role === 'admin' || user.role?.name === 'admin';

    return (
        <Shell>
            <div className="flex items-center justify-between rounded-lg px-3 py-2 text-body-sm border"
                style={{ backgroundColor: 'var(--bg-panel)', borderColor: 'var(--border-subtle)' }}>
                <span className="text-text-secondary truncate">
                    Signed in as <span className="text-text-primary">{user.display_name || user.name}</span>
                    <span className="text-text-tertiary"> · {user.role?.name || user.role}</span>
                </span>
                <button onClick={logout} className="text-label-sm font-medium shrink-0 ml-2" style={{ color: 'var(--accent-primary)' }}>
                    Switch account
                </button>
            </div>

            <p className="text-body-sm text-text-tertiary text-center">
                Connect a runtime daemon to this workspace.
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
