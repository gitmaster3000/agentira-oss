import React, { useEffect, useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { api } from '../api';
import { ROUTES } from '../routes';
import { mcpAuthorizeTarget, postToMcp } from '../mcpConnect';

// /mcp-connect?return=<MCP authorize URL>: an MCP client (Claude Code, a connector) sent the user to the
// MCP service to sign in. Logged in here → hand the login over, no password. Logged out → Agentira login first.
// A return address that is not the configured MCP service goes home and never receives the login.
export function McpConnect() {
    const { user, loading } = useAuth();
    const location = useLocation();
    const returnUrl = new URLSearchParams(location.search).get('return') || '';
    const [rejected, setRejected] = useState(false);

    useEffect(() => {
        if (loading || !user) return;
        let alive = true;
        api.getAuthConfig()
            .then(({ mcp_url }) => {
                const target = mcpAuthorizeTarget(returnUrl, mcp_url);
                if (!target) throw new Error('not the MCP service');
                postToMcp(target);
            })
            .catch(() => { if (alive) setRejected(true); });
        return () => { alive = false; };
    }, [loading, user, returnUrl]);

    if (loading) return <div>Loading...</div>;
    if (!user) return <Navigate to={ROUTES.LOGIN} state={{ from: location }} replace />;
    if (rejected) return <Navigate to={ROUTES.STUDIO} replace />;
    return <div style={{ padding: 16, textAlign: 'center', color: 'var(--text-secondary)' }}>Connecting you to Agentira…</div>;
}
