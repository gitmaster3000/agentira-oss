import React, { useState, useEffect } from 'react';
import { Trash2, Paperclip } from 'lucide-react';
import { api } from '../api';
import { ConfirmModal } from './ConfirmModal';

export function TaskCard({ task, onUpdate, onDelete }) {
    const [isConfirmingDelete, setIsConfirmingDelete] = useState(false);

    const [attachmentsCount, setAttachmentsCount] = useState(0);

    useEffect(() => {
        let isMounted = true;
        if (task.attachments_count !== undefined) {
            setAttachmentsCount(task.attachments_count);
            return;
        }

        api.listAttachments(task.id)
            .then(atts => {
                if (isMounted && atts && atts.length > 0) {
                    setAttachmentsCount(atts.length);
                }
            })
            .catch(err => console.error('Failed to load attachments for card:', err));
        return () => { isMounted = false; };
    }, [task.id, task.attachments_count]);

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

    const statusColor = task.priority === 'critical' ? 'var(--status-review)'
        : task.priority === 'high' ? 'var(--status-inprogress)'
        : task.priority === 'medium' ? 'var(--status-todo)'
        : 'var(--status-backlog)';

    return (
        <div
            draggable
            onDragStart={handleDragStart}
            onClick={(e) => { e.stopPropagation(); onUpdate(task); }}
            className="card mb-3 cursor-pointer hover:bg-bg-hover transition-colors group relative"
            style={{
                backgroundColor: 'var(--bg-card)',
                borderLeft: `3px solid ${statusColor}`,
            }}
        >
            {/* Delete button */}
            <button
                onClick={(e) => { e.stopPropagation(); setIsConfirmingDelete(true); }}
                className="absolute top-2 right-2 p-1 rounded-sm opacity-0 group-hover:opacity-100 transition-opacity z-10"
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

            <div className="flex justify-between items-start mb-1 h-10">
                <h4 className="font-medium text-body-md text-text-primary line-clamp-2 pr-6">{task.title}</h4>
            </div>

            <div className="flex justify-between items-center mt-2">
                <div className="flex items-center gap-2">
                    {task.epic_name && (
                        <span 
                            className="text-[10px] font-bold px-1.5 py-0.5 rounded-sm uppercase tracking-wider"
                            style={{ backgroundColor: `${task.epic_color || '#7c4dff'}20`, color: task.epic_color || '#7c4dff' }}
                            title={`Epic: ${task.epic_name}`}
                        >
                            {task.epic_name}
                        </span>
                    )}
                    <span className={`text-xs font-semibold px-2 py-0.5 rounded-sm capitalize ${
                        task.priority === 'critical' ? 'bg-red-500/20 text-red-400' : 'bg-bg-panel text-text-secondary'
                    }`}>
                        {task.priority}
                    </span>
                    {attachmentsCount > 0 && (
                        <span className="flex items-center gap-1 text-label-sm text-text-tertiary bg-bg-panel px-1.5 py-0.5 rounded-sm" title={`${attachmentsCount} attachment(s)`}>
                            <Paperclip className="w-3 h-3" /> {attachmentsCount}
                        </span>
                    )}
                </div>
                {task.assignee && (
                    <span className="text-label-sm text-text-secondary bg-bg-panel px-2 py-0.5 rounded-sm" title={task.assignee}>
                        {task.assignee.slice(0, 2).toUpperCase()}
                    </span>
                )}
            </div>
        </div>
    );
}
