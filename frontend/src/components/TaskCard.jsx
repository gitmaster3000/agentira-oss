import React, { useState, memo } from 'react';
import { Link } from 'react-router-dom';
import { Trash2 } from 'lucide-react';
import { api } from '../api';
import { ROUTES } from '../routes';
import { ConfirmModal } from './ConfirmModal';

// Priority pill colors. Hex matches the design tokens
// (tokens/colors.css --priority-*) — these are theme-independent accents.
const PRIORITY = {
    critical: { color: '#f85149', bg: 'rgba(248,81,73,.14)' },
    high:     { color: '#ff9800', bg: 'rgba(255,152,0,.14)' },
    medium:   { color: '#7c8db5', bg: 'rgba(124,141,181,.14)' },
    low:      { color: '#768390', bg: 'rgba(118,131,144,.14)' },
};

export const TaskCard = memo(function TaskCard({ task, onUpdate, onDelete }) {
    const [isConfirmingDelete, setIsConfirmingDelete] = useState(false);

    const handleDragStart = (e) => {
        e.dataTransfer.setData('taskId', task.id);
    };

    const handleDeleteClick = async (e) => {
        e.stopPropagation();
        try {
            await api.deleteTask(task.id);
            if (onDelete) onDelete();
        } catch (err) {
            alert(err.message);
            setIsConfirmingDelete(false);
        }
    };

    const live = task.agent_active;
    const prio = PRIORITY[task.priority] || PRIORITY.medium;
    // No priority color on the left edge — only the live-agent indicator,
    // which appears just for active tasks. Priority still reads via its pill.
    const leftBorder = live ? '#38bdf8' : 'var(--border-subtle)';

    return (
        <div
            draggable
            onDragStart={handleDragStart}
            onClick={(e) => { e.stopPropagation(); onUpdate(task); }}
            className={`group relative cursor-pointer ${live ? 'agent-active-glow' : ''}`}
            style={{
                background: 'var(--bg-card)',
                border: '1px solid var(--border-subtle)',
                borderLeft: `3px solid ${leftBorder}`,
                borderRadius: 6,
                padding: 10,
            }}
            title={live ? 'An agent is working on this task' : undefined}
        >
            {/* Delete (hover only) */}
            <button
                onClick={(e) => { e.stopPropagation(); setIsConfirmingDelete(true); }}
                className="absolute top-1.5 right-1.5 p-1 rounded-sm opacity-0 group-hover:opacity-100 transition-opacity z-10"
                style={{ color: 'var(--text-tertiary)', backgroundColor: 'var(--bg-panel)' }}
                title="Delete task"
            >
                <Trash2 className="w-3.5 h-3.5" />
            </button>

            {isConfirmingDelete && (
                <ConfirmModal
                    title="Delete Task"
                    message={`Are you sure you want to delete task "${task.title}"?`}
                    confirmText="Delete"
                    onConfirm={handleDeleteClick}
                    onCancel={(e) => { e?.stopPropagation(); setIsConfirmingDelete(false); }}
                />
            )}

            {/* Key + live / needs-attention */}
            <div className="flex items-center justify-between" style={{ marginBottom: 5 }}>
                <span style={{ fontSize: 10.5, fontFamily: 'ui-monospace,monospace', color: '#7c8db5' }}>
                    {task.key || task.id}
                </span>
                {live ? (
                    <span className="flex items-center" style={{ gap: 4 }}>
                        <span style={{ width: 13, height: 13, borderRadius: 4, background: 'rgba(0,188,212,.16)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                            <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="#00bcd4" strokeWidth="2.6"><rect x="3" y="11" width="18" height="10" rx="2"></rect><circle cx="12" cy="5" r="2"></circle></svg>
                        </span>
                        <span style={{ fontSize: 9, fontWeight: 700, color: '#38bdf8' }}>LIVE</span>
                    </span>
                ) : task.needs_attention ? (
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#ff9800" strokeWidth="2" title="Needs attention"><path d="M12 9v4M12 17h.01"></path><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path></svg>
                ) : null}
            </div>

            {/* Title */}
            <div style={{ fontSize: 12, lineHeight: 1.35, marginBottom: 9, color: 'var(--text-primary)' }} className="line-clamp-2 pr-5">
                {task.title}
            </div>

            {/* Epic + priority · assignee */}
            <div className="flex items-center justify-between">
                <div className="flex items-center" style={{ gap: 5 }}>
                    {task.epic_name && (
                        task.epic_id ? (
                            <Link
                                to={ROUTES.STUDIO_EPIC(task.epic_id)}
                                onClick={(e) => e.stopPropagation()}
                                style={{ fontSize: 9, fontWeight: 700, padding: '2px 6px', borderRadius: 3, textTransform: 'uppercase', letterSpacing: '.03em', background: `${task.epic_color || '#c9b8ff'}22`, color: task.epic_color || '#c9b8ff' }}
                                className="hover:underline"
                                title={`Open epic: ${task.epic_name}`}
                            >
                                {task.epic_name}
                            </Link>
                        ) : (
                            <span
                                style={{ fontSize: 9, fontWeight: 700, padding: '2px 6px', borderRadius: 3, textTransform: 'uppercase', letterSpacing: '.03em', background: `${task.epic_color || '#c9b8ff'}22`, color: task.epic_color || '#c9b8ff' }}
                                title={`Epic: ${task.epic_name}`}
                            >
                                {task.epic_name}
                            </span>
                        )
                    )}
                    {task.priority && (
                        <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 6px', borderRadius: 3, textTransform: 'capitalize', background: prio.bg, color: prio.color }}>
                            {task.priority}
                        </span>
                    )}
                </div>
                {task.assignee && (
                    <span
                        style={{ width: 20, height: 20, borderRadius: '50%', background: 'var(--bg-panel)', color: 'var(--text-secondary)', fontSize: 9, fontWeight: 700 }}
                        className="flex items-center justify-center flex-shrink-0"
                        title={task.assignee}
                    >
                        {task.assignee.slice(0, 2).toUpperCase()}
                    </span>
                )}
            </div>
        </div>
    );
});
