import React, { useState, useEffect, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import { api } from '../api';
import { ColumnCanvas } from '../components/workflow/ColumnCanvas';
import { RuleCodePane } from '../components/workflow/RuleCodePane';
import { gateConditions } from '../lib/workflowRules';

// Workflow Engine page — a port of the design's "Workflow Engine.dc.html".
// A single framed engine card: toolbar (title + transition breadcrumb +
// Visual/Code toggle) over a canvas that reads board zone → process zone →
// gate zone. All data is real (getBoard + getProjectWorkflow); the marketing
// hero / three-views / isolation sections of the design file are not part of
// the in-app page.

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
    const to = gateConditions(selected, flow).to;

    return (
        <div style={{ height: '100%', overflowY: 'auto', background: '#0e1117', padding: '28px 32px 60px' }}>
            <style>{'@keyframes pulsedot{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.35;transform:scale(.78)}}'}</style>

            {/* page heading */}
            <div style={{ maxWidth: '1120px', margin: '0 auto 22px' }}>
                <h1 style={{ margin: '0 0 8px', fontSize: '24px', fontWeight: 600, letterSpacing: '-0.02em', color: '#f0f3f6' }}>Workflow Engine</h1>
                <p style={{ margin: 0, fontSize: '14px', lineHeight: 1.55, color: '#b1bac4', maxWidth: '64ch' }}>
                    Every column on the board gets its own rules: a <strong style={{ color: '#e8ebf0', fontWeight: 600 }}>process</strong> that routes work in on arrival, and a <strong style={{ color: '#e8ebf0', fontWeight: 600 }}>gate</strong> that verifies evidence before work is allowed out.
                </p>
            </div>

            {/* engine card */}
            <div style={{ maxWidth: '1120px', margin: '0 auto', background: '#14161b', border: '1px solid #30363d', borderRadius: '16px', boxShadow: '0 30px 80px rgba(0,0,0,.55)', overflow: 'hidden' }}>
                {/* toolbar */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '11px', padding: '13px 16px', borderBottom: '1px solid #30363d', background: '#161b22', flexWrap: 'wrap' }}>
                    <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: '22px', height: '22px', borderRadius: '6px', background: 'rgba(128,203,196,.14)' }}>
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#80cbc4" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="6" cy="6" r="2.5" /><circle cx="18" cy="18" r="2.5" /><path d="M8.5 6H15a3 3 0 0 1 3 3v6.5" /></svg>
                    </span>
                    <span style={{ fontSize: '13px', fontWeight: 600, color: '#f0f3f6' }}>Workflow Engine</span>
                    <span style={{ fontFamily: 'ui-monospace,SFMono-Regular,Menlo,monospace', fontSize: '11px', color: '#768390' }}>{projectName} · {selected} → {to || '(terminal)'}</span>
                    <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '7px' }}>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '11px', fontWeight: 600, color: '#c9b8ff', background: 'rgba(201,184,255,.1)', border: '1px solid rgba(201,184,255,.3)', borderRadius: '6px', padding: '4px 11px', lineHeight: 1.5, opacity: 0.6, cursor: 'not-allowed' }} title="Coming soon">
                            <svg width="11" height="11" viewBox="0 0 24 24" fill="#c9b8ff" stroke="none"><path d="M12 2.5l1.9 5.7 5.7 1.9-5.7 1.9L12 17.7l-1.9-5.7L4.4 10l5.7-1.9z" /></svg>Build with AI
                        </span>
                        <span style={{ width: '1px', height: '18px', background: '#30363d', margin: '0 2px' }} />
                        <ToggleBtn active={view === 'visual'} onClick={() => setView('visual')}>Visual</ToggleBtn>
                        <ToggleBtn active={view === 'code'} onClick={() => setView('code')}>Code</ToggleBtn>
                    </div>
                </div>

                {view === 'visual' ? (
                    <ColumnCanvas
                        columnNames={columnNames}
                        tasksByColumn={board.columns}
                        selected={selected}
                        onSelect={setSelected}
                        flow={flow}
                        project={projectName}
                    />
                ) : (
                    <RuleCodePane columnName={selected} flow={flow} />
                )}
            </div>

            <p style={{ maxWidth: '60ch', margin: '16px auto 0', fontSize: '13px', color: '#768390', textAlign: 'center' }}>
                Selecting a column shows its process and gate. The agent does the work, but the platform — never the agent — gathers the evidence behind a gate.
            </p>
        </div>
    );
}
