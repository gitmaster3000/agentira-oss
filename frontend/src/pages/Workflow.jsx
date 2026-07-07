import React, { useState, useEffect, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import { api } from '../api';
import { ColumnCanvas } from '../components/workflow/ColumnCanvas';
import { ColumnPanel } from '../components/workflow/ColumnPanel';
import { RuleCodePane } from '../components/workflow/RuleCodePane';
import { gateConditions } from '../lib/workflowRules';

// Workflow Engine page — a port of the design's "Workflow Engine.dc.html".
// Fills the content area directly below the app top bar (no page heading, no
// framing card). Left: the board as a sequence, gates at a glance. Right: a
// side panel with the selected column's process, its real gate checks, and the
// prompt handed to the agent. Data is real (getBoard + getProjectWorkflow);
// gate checks + prompts come from the backend's columns_ui, never a UI copy.

function ToggleBtn({ active, onClick, children }) {
    return (
        <button
            onClick={onClick}
            style={{
                fontFamily: 'inherit', fontSize: '11px', fontWeight: 600, borderRadius: '6px',
                padding: '4px 12px', margin: 0, cursor: 'pointer', lineHeight: 1.5,
                ...(active
                    ? { color: '#f0f3f6', background: '#1c2128', border: '1px solid #484f58' }
                    : { color: '#768390', background: 'transparent', border: '1px solid transparent' }),
            }}
        >{children}</button>
    );
}

export function Workflow() {
    const { projectId } = useParams();
    const [board, setBoard] = useState(null);
    const [flow, setFlow] = useState(null);
    const [columnsUi, setColumnsUi] = useState(null);
    const [selected, setSelected] = useState(null);
    const [view, setView] = useState('visual');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const load = useCallback(async () => {
        try {
            const [boardData, workflowData] = await Promise.all([
                api.getBoard(projectId),
                api.getProjectWorkflow(projectId),
            ]);
            setBoard(boardData);
            setFlow(workflowData.flow);
            setColumnsUi(workflowData.columns_ui || {});
            setSelected((prev) => prev || Object.keys(boardData.columns || {})[0] || null);
            setError(null);
        } catch (err) {
            setError(err.message || 'Failed to load workflow');
        } finally {
            setLoading(false);
        }
    }, [projectId]);

    useEffect(() => { load(); }, [load]);

    if (loading) return <div className="p-8 text-center text-secondary">Loading workflow...</div>;
    if (error) return <div className="p-8 text-center text-secondary">{error}</div>;
    if (!board || !flow || !selected) return <div className="p-8 text-center text-secondary">Workflow not found</div>;

    const columnNames = Object.keys(board.columns);
    const projectName = board.project?.name || 'project';
    const to = gateConditions(selected, flow, columnsUi).to;

    return (
        <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: '#0e1117', minHeight: 0 }}>
            <style>{'@keyframes pulsedot{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.35;transform:scale(.78)}}'}</style>

            {/* toolbar — sits right under the top bar */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '11px', padding: '13px 20px', borderBottom: '1px solid #30363d', background: '#161b22', flexWrap: 'wrap', flexShrink: 0 }}>
                <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: '22px', height: '22px', borderRadius: '6px', background: 'rgba(128,203,196,.14)' }}>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#80cbc4" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="6" cy="6" r="2.5" /><circle cx="18" cy="18" r="2.5" /><path d="M8.5 6H15a3 3 0 0 1 3 3v6.5" /></svg>
                </span>
                <h1 style={{ margin: 0, fontSize: '13px', fontWeight: 600, color: '#f0f3f6' }}>Workflow Engine</h1>
                <span style={{ fontFamily: 'ui-monospace,SFMono-Regular,Menlo,monospace', fontSize: '11px', color: '#768390' }}>{projectName} · {selected} → {to || '(terminal)'}</span>
                <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '7px' }}>
                    <ToggleBtn active={view === 'visual'} onClick={() => setView('visual')}>Visual</ToggleBtn>
                    <ToggleBtn active={view === 'code'} onClick={() => setView('code')}>Code</ToggleBtn>
                </div>
            </div>

            {/* body: board overview (left) + per-column detail (right) */}
            <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
                <div style={{ flex: 1, minWidth: 0, overflow: 'auto' }}>
                    <ColumnCanvas
                        columnNames={columnNames}
                        tasksByColumn={board.columns}
                        selected={selected}
                        onSelect={setSelected}
                        flow={flow}
                        columnsUi={columnsUi}
                    />
                </div>
                <div style={{ width: '380px', flexShrink: 0, borderLeft: '1px solid #30363d', background: '#0e1117', overflowY: 'auto' }}>
                    {view === 'visual'
                        ? <ColumnPanel columnName={selected} flow={flow} columnsUi={columnsUi} projectId={projectId} onPromptSaved={load} />
                        : <RuleCodePane columnName={selected} flow={flow} columnsUi={columnsUi} />}
                </div>
            </div>
        </div>
    );
}
