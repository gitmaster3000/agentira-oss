import React, { useState, useEffect, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import { api } from '../api';
import { ColumnCanvas } from '../components/workflow/ColumnCanvas';
import { RuleCodePane } from '../components/workflow/RuleCodePane';
import { RecentFiresPanel } from '../components/workflow/RecentFiresPanel';

// Board strip — every column of the project pipeline, selectable. Order and
// live counts come from the board (backend/services.py get_board, ordered by
// Status.position); rule content comes from the workflow config (§ below).
function BoardStrip({ columnNames, counts, selected, onSelect }) {
    return (
        <div className="flex items-center gap-2 px-4 py-3 border-b border-border-subtle overflow-x-auto shrink-0">
            {columnNames.map((name) => (
                <button
                    key={name}
                    onClick={() => onSelect(name)}
                    className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-label-lg whitespace-nowrap transition-colors border ${
                        selected === name
                            ? 'border-accent-primary text-primary bg-bg-card'
                            : 'border-border-subtle text-secondary hover:text-primary hover:border-border-active'
                    }`}
                >
                    <span>{name}</span>
                    <span className="text-label-sm text-tertiary bg-bg-app rounded-full px-1.5 py-0.5">{counts[name] ?? 0}</span>
                </button>
            ))}
        </div>
    );
}

export function Workflow() {
    const { projectId } = useParams();
    const [board, setBoard] = useState(null);
    const [flow, setFlow] = useState(null);
    const [selected, setSelected] = useState(null);
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
            setSelected((prev) => prev || workflowData.flow?.columns?.[0]?.name || null);
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
    if (!board || !flow) return <div className="p-8 text-center text-secondary">Workflow not found</div>;

    const columnNames = Object.keys(board.columns);
    const counts = Object.fromEntries(columnNames.map((name) => [name, board.columns[name].length]));

    return (
        <div className="flex flex-col h-full overflow-hidden">
            <BoardStrip columnNames={columnNames} counts={counts} selected={selected} onSelect={setSelected} />
            <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-4">
                {selected && (
                    <>
                        <ColumnCanvas columnName={selected} flow={flow} />
                        <RuleCodePane columnName={selected} flow={flow} />
                        <RecentFiresPanel />
                    </>
                )}
            </div>
        </div>
    );
}
