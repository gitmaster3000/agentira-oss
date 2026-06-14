import React, { useState } from 'react';
import { useSearchParams, Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { api } from '../api';
import { ROUTES } from '../routes';
import { Pencil, Terminal } from 'lucide-react';

export function CliAuth() {
    const { user, loading } = useAuth();
    const location = useLocation();
    const [params] = useSearchParams();
    const [code, setCode] = useState(params.get('user_code') || '');
    const [status, setStatus] = useState('idle'); // idle | working | done | error
    const [error, setError] = useState('');

    if (loading) return <div className="h-full flex items-center justify-center text-text-tertiary">Loading…</div>;
    // Must be signed in — send them to login, return here afterward.
    if (!user) return <Navigate to={ROUTES.LOGIN} state={{ from: location }} replace />;

    const isAdmin = user.role === 'admin' || user.role?.name === 'admin';

    const approve = async () => {
        setError(''); setStatus('working');
        try {
            await api.approveCliLogin(code.trim().toUpperCase());
            setStatus('done');
        } catch (err) {
            setError(err.message || 'Failed to authorize'); setStatus('error');
        }
    };

    return (
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
                        <p className="text-body-sm text-text-tertiary">
                            Connect a runtime daemon to <span className="text-text-secondary">{user.display_name || user.name}</span>’s workspace.
                        </p>
                    </div>

                    {!isAdmin && (
                        <div className="p-3 text-body-sm text-amber-400 bg-amber-900/20 border border-amber-800 rounded-md">
                            Only admins can connect a daemon. Sign in with an admin account.
                        </div>
                    )}

                    {status === 'done' ? (
                        <div className="p-3 text-body-sm text-green-400 bg-green-900/20 border border-green-800 rounded-md text-center">
                            ✓ Daemon authorized. You can return to your terminal.
                        </div>
                    ) : (
                        <>
                            {error && <div className="p-3 text-body-sm text-red-400 bg-red-900/20 border border-red-800 rounded-md">{error}</div>}
                            <div>
                                <label className="text-label-md text-text-secondary mb-1 block">Device code</label>
                                <input value={code} onChange={(e) => setCode(e.target.value)}
                                    className="input tracking-widest text-center uppercase" placeholder="ABC123" autoFocus />
                            </div>
                            <button onClick={approve} disabled={!isAdmin || !code.trim() || status === 'working'}
                                className="btn btn-primary w-full justify-center text-body-md">
                                {status === 'working' ? 'Authorizing…' : 'Authorize daemon'}
                            </button>
                        </>
                    )}
                </div>
            </div>
        </div>
    );
}
