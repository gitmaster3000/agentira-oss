import React from 'react';
import { initials } from './PanelFeed';

// Board status → dot color + label (design: guidelines/colors-semantic.html).
const STATUS = {
    backlog:     { color: 'var(--text-muted)', label: 'Backlog' },
    todo:        { color: '#8ab4f8', label: 'To Do' },
    in_progress: { color: '#ff9800', label: 'In Progress' },
    review:      { color: '#7c4dff', label: 'In Review' },
    done:        { color: '#2ecc71', label: 'Done' },
};

// Status / priority / assignee / epic / due: inline-editable, saved on change.
export function PanelFields({ task, members, epics, saveStatus, saveField }) {
    const status = STATUS[task.status] || { color: 'var(--text-muted)', label: task.status };
    return (
        <div style={{ display: 'grid', gridTemplateColumns: '84px 1fr', gap: '12px 10px', fontSize: 12.5, alignItems: 'center', marginBottom: 18 }}>
            <span className="text-text-tertiary">Status</span>
            <span className="inline-flex items-center" style={{ gap: 7 }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: status.color, flexShrink: 0 }} />
                <select className="ghost-select" value={task.status} onChange={e => saveStatus(e.target.value)}>
                    {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
                </select>
            </span>
            <span className="text-text-tertiary">Priority</span>
            <span>
                <select className="ghost-select capitalize" value={task.priority} onChange={e => saveField({ priority: e.target.value })}>
                    {['low', 'medium', 'high', 'critical'].map(p => <option key={p} value={p}>{p}</option>)}
                </select>
            </span>
            <span className="text-text-tertiary">Assignee</span>
            <span className="inline-flex items-center" style={{ gap: 7 }}>
                <span style={{ width: 20, height: 20, borderRadius: '50%', background: 'rgba(0,188,212,.16)', color: '#00bcd4', fontSize: 9, fontWeight: 700, flexShrink: 0 }} className="flex items-center justify-center">
                    {initials(task.assignee)}
                </span>
                <select className="ghost-select" value={task.assignee || ''} onChange={e => saveField({ assignee: e.target.value })}>
                    <option value="">Unassigned</option>
                    {members.map(p => <option key={p.id} value={p.name}>{p.display_name}</option>)}
                </select>
            </span>
            <span className="text-text-tertiary">Epic</span>
            <span className="inline-flex items-center" style={{ gap: 7 }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: task.epic_id ? (task.epic_color || 'var(--brand-lavender)') : 'transparent', flexShrink: 0 }} />
                <select aria-label="Epic" className="ghost-select" value={task.epic_id || ''} onChange={e => saveField({ epic_id: e.target.value })}>
                    <option value="">No epic</option>
                    {epics.map(ep => <option key={ep.id} value={ep.id}>{ep.title}</option>)}
                </select>
            </span>
            <span className="text-text-tertiary">Due</span>
            <span className="inline-flex items-center" style={{ gap: 7 }}>
                <input
                    type="date"
                    aria-label="Due date"
                    className="input input-date text-xs py-1 px-2 w-auto"
                    // Date input wants YYYY-MM-DD; clear with "" (backend → null).
                    value={task.due_date ? String(task.due_date).slice(0, 10) : ''}
                    onChange={e => saveField({ due_date: e.target.value || '' })}
                />
            </span>
        </div>
    );
}
