import React from 'react';
import { McpServersPanel } from '../../components/mcp/McpServersPanel';

const EZINE_MCP_URL = import.meta.env.VITE_EZINE_MCP_URL || 'https://ezine.up.railway.app/mcp';

export function McpServers() {
    return (
        <div style={{ maxWidth: 720, padding: '24px 8px' }}>
            <h1 style={{ fontSize: 22, fontWeight: 700, margin: '0 0 16px', color: 'var(--text-primary)' }}>MCP Servers</h1>
            <McpServersPanel ezineUrl={EZINE_MCP_URL} />
        </div>
    );
}
