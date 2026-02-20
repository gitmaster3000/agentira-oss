import React, { useState, useEffect } from 'react';
import { Trash2, Paperclip } from 'lucide-react';
import { api } from '../api';
import { ConfirmModal } from './ConfirmModal';

export function TaskCard({ task, onUpdate, onDelete }) {
    const [isConfirmingDelete, setIsConfirmingDelete] = useState(false);
    const priorityColors = {
        low: 'border-l-4 border-l-blue-400',
        medium: 'border-l-4 border-l-yellow-400',
        high: 'border-l-4 border-l-orange-500',
        critical: 'border-l-4 border-l-red-600',
    };

    const borderColor = priorityColors[task.priority] || 'border-l-4 border-l-gray-500';

    const [attachmentsCount, setAttachmentsCount] = useState(0);

    useEffect(() => {
        let isMounted = true;
        // Future proofing: if the backend adds attachments_count directly to task serialization
        if (task.attachments_count !== undefined) {
            setAttachmentsCount(task.attachments_count);
            return;
        }

        // Fallback: fetch from API
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

    return (
        <div
            draggable
            onDragStart={handleDragStart}
            onClick={(e) => { e.stopPropagation(); onUpdate(task); }}
            className={`card mb-3 cursor-pointer hover:bg-bg-hover transition-colors group relative ${borderColor}`}
            style={{
                backgroundColor: 'var(--bg-card)',
                borderLeft: `4px solid var(--status-${task.priority === 'critical' ? 'review' : task.priority === 'high' ? 'inprogress' : 'todo'})`
            }}
        >
            {/* Delete button — visible on hover */}
            <button
                onClick={(e) => { e.stopPropagation(); setIsConfirmingDelete(true); }}
                className="absolute top-1.5 right-1.5 p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity z-10"
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

            <div className="flex justify-between items-start mb-1">
                <h4 className="font-medium text-sm text-primary line-clamp-2 pr-6">{task.title}</h4>
            </div>

            <div className="flex justify-between items-center mt-2">
                <div className="flex items-center gap-2">
                    <span className={`text-xs px-1.5 py-0.5 rounded capitalize ${task.priority === 'critical' ? 'bg-red-900 text-red-100' : 'bg-bg-panel text-secondary'
                        }`}>
                        {task.priority}
                    </span>
                    {attachmentsCount > 0 && (
                        <span className="flex items-center gap-1 text-[10px] text-text-tertiary font-medium bg-bg-panel px-1.5 py-0.5 rounded" title={`${attachmentsCount} attachment(s)`}>
                            <Paperclip className="w-3 h-3" /> {attachmentsCount}
                        </span>
                    )}
                </div>
                {task.assignee && (
                    <span className="text-xs text-secondary bg-bg-panel px-1.5 py-0.5 rounded" title={task.assignee}>
                        {task.assignee.slice(0, 2).toUpperCase()}
                    </span>
                )}
            </div>
        </div>
    );
}
