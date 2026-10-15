import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Trash2, X, ExternalLink, Pencil, Check } from 'lucide-react';
import { ROUTES } from '../../routes';

// Header: key · open full / edit / delete / close. Fixed 53px height matches
// the board toolbar so the panel's top divider lines up with the board
// header's bottom border. While editing, edit/delete swap to Save/Cancel — the
// same standard used on the Epic page.
export function PanelHeader({ task, isEditing, onSave, onCancel, onEdit, onDelete, onClose }) {
    const navigate = useNavigate();
    return (
        <div className="flex items-center gap-2 flex-shrink-0" style={{ padding: '0 18px', height: 53, borderBottom: '1px solid var(--border-subtle)' }}>
            <span style={{ fontSize: 12, fontFamily: 'ui-monospace,monospace', fontWeight: 600, color: 'var(--accent-mono-blue)', whiteSpace: 'nowrap' }}>
                {task.key || task.id}
            </span>
            <div className="flex-1" />
            {isEditing ? (
                <>
                    <button onClick={onSave} title="Save changes" className="flex items-center gap-1.5 transition-colors" style={{ padding: '6px 12px', borderRadius: 8, fontSize: 11.5, fontWeight: 600, background: 'var(--accent-primary)', color: '#fff' }}>
                        <Check className="w-3.5 h-3.5" /> Save
                    </button>
                    <button onClick={onCancel} title="Cancel" className="flex items-center gap-1.5 text-text-secondary hover:text-text-primary transition-colors" style={{ padding: '6px 11px', borderRadius: 8, border: '1px solid var(--border-subtle)', fontSize: 11.5, fontWeight: 500 }}>
                        <X className="w-3.5 h-3.5" /> Cancel
                    </button>
                </>
            ) : (
                <>
                    <button
                        onClick={() => navigate(ROUTES.STUDIO_TASK(task.key || task.id))}
                        className="flex items-center gap-1.5 text-text-tertiary hover:text-text-primary transition-colors"
                        style={{ padding: '6px 11px', borderRadius: 8, border: '1px solid var(--border-subtle)', fontSize: 11.5 }}
                        title="Open full task page"
                    >
                        <ExternalLink className="w-3 h-3" /> Open full
                    </button>
                    <button onClick={onEdit} title="Edit" className="flex items-center justify-center text-text-tertiary hover:text-text-primary hover:bg-bg-card transition-colors" style={{ width: 28, height: 28, borderRadius: 8 }}>
                        <Pencil className="w-4 h-4" />
                    </button>
                    <button onClick={onDelete} title="Delete" className="flex items-center justify-center text-text-tertiary hover:text-red-400 transition-colors" style={{ width: 28, height: 28, borderRadius: 8 }}>
                        <Trash2 className="w-4 h-4" />
                    </button>
                    {/* In edit mode the Cancel button covers dismissal, so the
                        standalone close (X) is hidden to avoid a redundant cross. */}
                    <button onClick={onClose} title="Close" className="flex items-center justify-center text-text-tertiary hover:text-text-primary hover:bg-bg-card transition-colors" style={{ width: 28, height: 28, borderRadius: 8 }}>
                        <X className="w-4 h-4" />
                    </button>
                </>
            )}
        </div>
    );
}
