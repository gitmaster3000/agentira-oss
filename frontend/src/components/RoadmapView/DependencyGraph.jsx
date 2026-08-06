import React, { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { ReactFlow, Background, Controls, MiniMap, MarkerType } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { GitBranch } from 'lucide-react';
import { ROUTES } from '../../routes';

const STATUS_COLORS = {
    done: '#2ecc71',
    review: '#ff9800',
    in_progress: '#7c4dff',
    todo: '#00bcd4',
    backlog: '#5f6368',
};

const COL_WIDTH = 240;
const ROW_HEIGHT = 90;

/**
 * Longest-path layering: a task sits one column right of everything it waits
 * on, so the graph reads left → right as "do this, then this". `seen` bounds
 * the walk — the backend rejects cycles, but a stale payload must never hang
 * the browser.
 */
function layer(taskIds, dependsOn) {
    const depth = new Map(taskIds.map(id => [id, 0]));
    const resolve = (id, seen) => {
        if (seen.has(id)) return 0;
        seen.add(id);
        const parents = dependsOn.get(id) || [];
        if (!parents.length) return 0;
        return 1 + Math.max(...parents.map(p => resolve(p, seen)));
    };
    for (const id of taskIds) depth.set(id, resolve(id, new Set()));
    return depth;
}

/**
 * Dependency DAG for the project. Only tasks that participate in at least one
 * dependency are drawn — an unconnected task is board work, not graph work,
 * and drawing all of them turns the canvas into confetti.
 */
export function DependencyGraph({ epics = [], dependencies = [], onRemoveDependency }) {
    const navigate = useNavigate();

    const { nodes, edges, connectedCount } = useMemo(() => {
        const byId = new Map();
        for (const epic of epics) {
            for (const task of epic.tasks || []) byId.set(task.id, { ...task, epic: epic.name });
        }
        const edgesIn = dependencies.filter(
            d => byId.has(d.task_id) && byId.has(d.depends_on_id));
        const connected = new Set();
        const dependsOn = new Map();
        for (const d of edgesIn) {
            connected.add(d.task_id);
            connected.add(d.depends_on_id);
            dependsOn.set(d.task_id, [...(dependsOn.get(d.task_id) || []), d.depends_on_id]);
        }

        const ids = [...connected];
        const depth = layer(ids, dependsOn);
        const rowCursor = new Map();

        const nodes = ids.map((id) => {
            const task = byId.get(id);
            const col = depth.get(id) || 0;
            const row = rowCursor.get(col) || 0;
            rowCursor.set(col, row + 1);
            const color = STATUS_COLORS[task.status] || STATUS_COLORS.backlog;
            return {
                id,
                position: { x: col * COL_WIDTH, y: row * ROW_HEIGHT },
                data: {
                    label: (
                        <div className="text-left">
                            <div className="text-[10px] font-mono opacity-70">{task.key}</div>
                            <div className="text-xs font-medium leading-tight">{task.title}</div>
                            <div className="text-[10px] opacity-70 mt-0.5">
                                {task.status.replace('_', ' ')}
                                {task.is_blocked ? ' · blocked' : ''}
                            </div>
                        </div>
                    ),
                },
                style: {
                    width: COL_WIDTH - 60,
                    padding: 8,
                    borderRadius: 8,
                    background: 'var(--bg-card)',
                    color: 'var(--text-primary)',
                    border: `1px solid ${task.is_blocked ? '#e74c3c' : color}`,
                    borderLeft: `4px solid ${color}`,
                    fontSize: 12,
                },
            };
        });

        const edges = edgesIn.map((d) => {
            const blocker = byId.get(d.depends_on_id);
            const satisfied = blocker.status === 'done';
            return {
                id: d.id,
                source: d.depends_on_id,   // blocker first: it must finish
                target: d.task_id,
                animated: !satisfied,
                style: { stroke: satisfied ? '#2ecc71' : '#e74c3c', strokeWidth: 1.5 },
                markerEnd: { type: MarkerType.ArrowClosed, color: satisfied ? '#2ecc71' : '#e74c3c' },
            };
        });

        return { nodes, edges, connectedCount: connected.size };
    }, [epics, dependencies]);

    if (!nodes.length) {
        return (
            <div className="card p-6 text-sm text-text-tertiary">
                <div className="flex items-center gap-2 text-text-primary font-medium mb-1">
                    <GitBranch className="w-4 h-4" />
                    Nothing depends on anything yet
                </div>
                Open a task and add a “waits on” link to say which work has to finish first.
                Anything you link shows up here as a chart.
            </div>
        );
    }

    return (
        <div className="card p-0 overflow-hidden">
            <div className="px-4 py-3 border-b border-border-subtle/40 flex items-center gap-2">
                <GitBranch className="w-4 h-4 text-text-tertiary" />
                <span className="text-xs font-medium text-text-primary uppercase tracking-wider">
                    Dependencies
                </span>
                <span className="text-xs text-text-tertiary ml-auto">
                    {connectedCount} linked tasks · {edges.length} links · red = still waiting
                </span>
            </div>
            <div style={{ height: 560 }}>
                <ReactFlow
                    nodes={nodes}
                    edges={edges}
                    fitView
                    nodesDraggable={false}
                    nodesConnectable={false}
                    proOptions={{ hideAttribution: false }}
                    onNodeClick={(_, node) => navigate(ROUTES.STUDIO_TASK(node.id))}
                    onEdgeClick={(_, edge) => {
                        if (!onRemoveDependency) return;
                        if (window.confirm('Remove this dependency link?')) onRemoveDependency(edge.id);
                    }}
                >
                    <Background gap={18} color="var(--border-subtle)" />
                    <Controls showInteractive={false} />
                    <MiniMap pannable zoomable style={{ background: 'var(--bg-panel)' }} />
                </ReactFlow>
            </div>
        </div>
    );
}
