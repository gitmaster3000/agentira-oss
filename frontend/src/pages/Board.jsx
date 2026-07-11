import React, { useMemo } from 'react';
import { useOutletContext, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { TaskCard } from '../components/TaskCard';

// Board status dot colors — from the design system (guidelines/colors-semantic.html).
const STATUS_COLORS = {
    backlog: '#768390',
    todo: '#8ab4f8',
    in_progress: '#ff9800',
    review: '#7c4dff',
    done: '#2ecc71',
};

const COLUMNS = [
    { id: 'backlog', label: 'Backlog' },
    { id: 'todo', label: 'To Do' },
    { id: 'in_progress', label: 'In Progress' },
    { id: 'review', label: 'Review' },
    { id: 'done', label: 'Done' },
];

export function Board() {
    const { searchQuery, filterPriority, filterAssignee, filterEpic, board, reloadBoard, applyMove, requestSelectTask } = useOutletContext();
    const [searchParams, setSearchParams] = useSearchParams();

    const handleDrop = async (e, status) => {
        const taskId = e.dataTransfer.getData('taskId');
        if (!taskId) return;

        // Optimistic update: move the card in UI immediately for snappy feel.
        // (Root cause of "7s move": no optimistic + full board reload after every move.)
        if (applyMove) applyMove(taskId, status);

        try {
            await api.moveTask(taskId, status);
            // Reconcile with server (picks up computed fields like agent_active).
            // Because we applied optimistic already, the user sees the move instantly;
            // this GET happens in the background of the perceived action.
            reloadBoard();
        } catch (err) {
            alert(err.message || "Failed to move task");
            reloadBoard();  // revert to server truth
        }
    };

    const filteredColumns = useMemo(() => {
        if (!board) return {};
        const filtered = {};
        for (const [colId, tasks] of Object.entries(board.columns)) {
            filtered[colId] = tasks.filter(task => {
                if (searchQuery && !task.title.toLowerCase().includes(searchQuery.toLowerCase())) return false;
                if (filterPriority && task.priority !== filterPriority) return false;
                if (filterAssignee && task.assignee !== filterAssignee) return false;
                if (filterEpic && String(task.epic_id) !== String(filterEpic)) return false;
                return true;
            });
        }
        return filtered;
    }, [board, searchQuery, filterPriority, filterAssignee, filterEpic]);

    return (
        <div className="h-full overflow-x-auto overflow-y-hidden p-3.5">
            <div className="h-full grid grid-cols-5 gap-2.5 min-w-[1080px] w-full">
                {COLUMNS.map(col => (
                    <div
                        key={col.id}
                        className="flex flex-col overflow-hidden"
                        style={{ backgroundColor: 'rgba(201,184,255,.04)', borderRadius: 8 }}
                        onDragOver={e => e.preventDefault()}
                        onDrop={e => handleDrop(e, col.id)}
                    >
                        <div
                            className="flex justify-between items-center flex-shrink-0"
                            style={{ padding: '10px 12px', borderBottom: '1px solid var(--border-subtle)' }}
                        >
                            <div className="flex items-center font-semibold" style={{ gap: 7, fontSize: 12.5 }}>
                                <span className="rounded-full" style={{ width: 9, height: 9, backgroundColor: STATUS_COLORS[col.id] }} />
                                {col.label}
                            </div>
                            <span className="rounded-full" style={{ fontSize: 10, padding: '1px 8px', backgroundColor: 'var(--bg-app)', color: 'var(--text-secondary)' }}>
                                {filteredColumns[col.id]?.length || 0}
                            </span>
                        </div>

                        <div className="flex-1 flex flex-col column-scroll" style={{ padding: 8, gap: 8 }}>
                            {filteredColumns[col.id]?.map(task => (
                                <TaskCard
                                    key={task.id}
                                    task={task}
                                    onUpdate={(t) => requestSelectTask(t.key || t.id)}
                                    onDelete={reloadBoard}
                                />
                            ))}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}
