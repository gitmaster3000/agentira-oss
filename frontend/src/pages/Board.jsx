import React from 'react';
import { useOutletContext, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { TaskCard } from '../components/TaskCard';

const STATUS_COLORS = {
    backlog: '#5f6368',
    todo: '#00bcd4',
    in_progress: '#7c4dff',
    review: '#ff9800',
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
    const { searchQuery, filterPriority, filterAssignee, filterEpic, board, reloadBoard } = useOutletContext();
    const [searchParams, setSearchParams] = useSearchParams();

    const handleDrop = async (e, status) => {
        const taskId = e.dataTransfer.getData('taskId');
        if (!taskId) return;
        try {
            await api.moveTask(taskId, status);
            reloadBoard();
        } catch (err) {
            alert(err.message || "Failed to move task");
            reloadBoard();
        }
    };

    const getFilteredColumns = () => {
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
    };
    const filteredColumns = getFilteredColumns();

    return (
        <div className="h-full overflow-x-auto overflow-y-hidden p-2 sm:p-3 lg:p-4">
            <div className="h-full grid grid-cols-5 gap-3 min-w-[1148px] w-full">
                {COLUMNS.map(col => (
                    <div
                        key={col.id}
                        className="flex flex-col rounded-md h-full overflow-hidden"
                        style={{ backgroundColor: 'var(--bg-surface-purple)' }}
                        onDragOver={e => e.preventDefault()}
                        onDrop={e => handleDrop(e, col.id)}
                    >
                        <div className="px-4 py-3 font-medium text-title-sm flex justify-between items-center border-b">
                            <div className="flex items-center gap-2">
                                <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: STATUS_COLORS[col.id] }} />
                                {col.label}
                            </div>
                            <span className="text-label-sm px-2.5 py-0.5 rounded-full" style={{ backgroundColor: 'var(--bg-app)', color: 'var(--text-secondary)' }}>
                                {filteredColumns[col.id]?.length || 0}
                            </span>
                        </div>

                        <div className="flex-1 pl-4 pr-2.5 py-2 column-scroll">
                            {filteredColumns[col.id]?.map(task => (
                                <TaskCard
                                    key={task.id}
                                    task={task}
                                    onClick={() => {
                                        const newParams = new URLSearchParams(searchParams);
                                        newParams.set('selectedTask', task.key || task.id);
                                        setSearchParams(newParams);
                                    }}
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
