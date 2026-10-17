import React, { useEffect, useState } from 'react';
import { Navigate, useLocation, useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { api } from '../api';
import { ROUTES } from '../routes';
import { Plug } from 'lucide-react';

const READ = 'agentira:read';
const WRITE = 'agentira:write';

// Consent page for connecting an MCP client (e.g. Claude) — the client never
// sees an API key; it receives a revocable, auto-refreshing connection.
export function McpAuthorize() {
    const { user, loading } = useAuth();
    const location = useLocation();
    const [params] = useSearchParams();
    const [clientName, setClientName] = useState('');
    const [allowChanges, setAllowChanges] = useState(
        (params.get('scope') || '').split(' ').includes(WRITE));
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const clientId = params.get('client_id') || '';

    useEffect(() => {
        if (!user || !clientId) return;
        api.getMcpClient(clientId).then((c) => setClientName(c.client_name))
            .catch(() => setError('This app is not recognised. Start the connection again from the app.'));
    }, [user, clientId]);

    if (loading) return <div className="p-6 text-text-tertiary text-body-sm">Loading…</div>;
    if (!user) return <Navigate to={ROUTES.LOGIN} replace state={{ from: location }} />;

    const decide = async (approve) => {
        setBusy(true); setError('');
        try {
            const res = await api.mcpAuthorize({
                approve, client_id: clientId, redirect_uri: params.get('redirect_uri'),
                state: params.get('state'), code_challenge: params.get('code_challenge'),
                code_challenge_method: params.get('code_challenge_method'),
                scope: allowChanges ? `${READ} ${WRITE}` : READ,
            });
            window.location.assign(res.redirect_url);
        } catch (err) {
            setError(err.message || 'Could not connect. Start again from the app.');
            setBusy(false);
        }
    };

    const name = clientName || 'An app';
    return (
        <div className="h-full bg-bg-app flex items-center justify-center px-4">
            <div className="card w-full max-w-sm space-y-5">
                <div className="text-center space-y-1">
                    <Plug className="w-6 h-6 mx-auto" style={{ color: 'var(--accent-primary)' }} />
                    <h2 className="text-headline-sm text-text-primary">Connect {name} to Agentira</h2>
                    <p className="text-body-sm text-text-tertiary">
                        Signed in as {user.display_name || user.name}. {name} will act as you.
                    </p>
                </div>
                {error && <div role="alert" className="p-3 text-body-sm text-red-400 bg-red-900/20 border border-red-800 rounded-md">{error}</div>}
                <div className="space-y-3 text-body-sm text-text-secondary">
                    <label className="flex items-start gap-2">
                        <input type="checkbox" checked disabled className="mt-1" />
                        <span>See your projects, tasks, comments and runs</span>
                    </label>
                    <label className="flex items-start gap-2">
                        <input type="checkbox" checked={allowChanges}
                            onChange={(e) => setAllowChanges(e.target.checked)} className="mt-1" />
                        <span>Create and change tasks, comments and projects</span>
                    </label>
                </div>
                <p className="text-label-sm text-text-tertiary">
                    {name} never sees your password or API key.
                </p>
                <div className="flex gap-2">
                    <button className="btn w-full justify-center" disabled={busy} onClick={() => decide(false)}>Cancel</button>
                    <button className="btn btn-primary w-full justify-center" disabled={busy || !clientName}
                        onClick={() => decide(true)}>{busy ? 'Connecting…' : 'Allow'}</button>
                </div>
            </div>
        </div>
    );
}
