import React, { useState } from 'react';
import { Flag, Plus, Trash2, Check, X } from 'lucide-react';
import { api } from '../../api';

const STATUS_LABEL = {
    planned: 'Planned',
    achieved: 'Hit',
    missed: 'Missed',
};

function daysAway(due) {
    if (!due) return null;
    const ms = new Date(due).setHours(0, 0, 0, 0) - new Date().setHours(0, 0, 0, 0);
    return Math.round(ms / 86400000);
}

function DueLabel({ milestone }) {
    if (!milestone.due_date) return <span className="text-xs text-text-tertiary">No date set</span>;
    const days = daysAway(milestone.due_date);
    const date = new Date(milestone.due_date).toLocaleDateString(
        undefined, { month: 'short', day: 'numeric', year: 'numeric' });
    // Plain language on purpose — a non-engineer owner reads this column.
    let hint = `in ${days} days`;
    if (days === 0) hint = 'today';
    else if (days === 1) hint = 'tomorrow';
    else if (days < 0) hint = `${Math.abs(days)} days ago`;
    const late = days < 0 && milestone.status !== 'achieved' && milestone.done < milestone.total;
    return (
        <span className={`text-xs ${late ? 'text-red-400' : 'text-text-tertiary'}`}>
            {date} · {hint}
        </span>
    );
}

function MilestoneRow({ milestone, onUpdate, onDelete }) {
    const pct = milestone.progress;
    return (
        <div className="px-4 py-3 border-t border-border-subtle/40 group">
            <div className="flex items-center gap-3">
                <Flag className="w-4 h-4 flex-shrink-0" style={{ color: milestone.color }} />
                <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-text-primary truncate">{milestone.title}</div>
                    <DueLabel milestone={milestone} />
                </div>
                <div className="flex items-center gap-2 w-40">
                    <div className="flex-1 h-1.5 rounded-full bg-bg-tertiary overflow-hidden">
                        <div className="h-full rounded-full transition-all"
                             style={{ width: `${pct}%`, backgroundColor: milestone.color }} />
                    </div>
                    <span className="text-xs text-text-tertiary whitespace-nowrap">
                        {milestone.done}/{milestone.total}
                    </span>
                </div>
                <select
                    value={milestone.status}
                    onChange={(e) => onUpdate(milestone.id, { status: e.target.value })}
                    className="text-xs bg-bg-panel border border-border-subtle rounded px-2 py-1 text-text-secondary"
                >
                    {Object.entries(STATUS_LABEL).map(([value, label]) => (
                        <option key={value} value={value}>{label}</option>
                    ))}
                </select>
                <button
                    onClick={() => onDelete(milestone)}
                    className="text-text-tertiary hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
                    title="Delete milestone"
                >
                    <Trash2 className="w-3.5 h-3.5" />
                </button>
            </div>
            {milestone.description && (
                <p className="text-xs text-text-tertiary mt-2 ml-7">{milestone.description}</p>
            )}
        </div>
    );
}

function NewMilestoneForm({ onCreate, onCancel }) {
    const [title, setTitle] = useState('');
    const [dueDate, setDueDate] = useState('');
    const [busy, setBusy] = useState(false);

    const submit = async (e) => {
        e.preventDefault();
        if (!title.trim() || busy) return;
        setBusy(true);
        try {
            await onCreate({ title: title.trim(), due_date: dueDate || null });
            setTitle('');
            setDueDate('');
        } finally {
            setBusy(false);
        }
    };

    return (
        <form onSubmit={submit} className="px-4 py-3 border-t border-border-subtle/40 flex items-center gap-2">
            <input
                autoFocus
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="What are you aiming for? e.g. Public beta"
                className="flex-1 text-sm bg-bg-panel border border-border-subtle rounded px-2 py-1.5 text-text-primary"
            />
            <input
                type="date"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
                className="text-sm bg-bg-panel border border-border-subtle rounded px-2 py-1.5 text-text-secondary"
            />
            <button type="submit" disabled={!title.trim() || busy}
                    className="text-green-400 disabled:opacity-40" title="Save">
                <Check className="w-4 h-4" />
            </button>
            <button type="button" onClick={onCancel} className="text-text-tertiary hover:text-text-primary" title="Cancel">
                <X className="w-4 h-4" />
            </button>
        </form>
    );
}

/**
 * Milestones = the dated things the team is aiming at. Progress is whatever
 * share of the tasks pointing at the milestone are done — it is computed by
 * the backend from the board, so it can never be talked up by hand.
 */
export function MilestonePanel({ projectId, milestones = [], onChanged }) {
    const [adding, setAdding] = useState(false);
    const [error, setError] = useState(null);

    const run = async (fn) => {
        setError(null);
        try {
            await fn();
            onChanged?.();
            return true;
        } catch (err) {
            setError(err.message || 'Something went wrong.');
            return false;
        }
    };

    const create = async (data) => {
        if (await run(() => api.createMilestone(projectId, data))) setAdding(false);
    };
    const update = (id, data) => run(() => api.updateMilestone(projectId, id, data));
    const remove = (ms) => {
        if (!window.confirm(`Delete milestone "${ms.title}"? Its tasks stay put.`)) return;
        run(() => api.deleteMilestone(projectId, ms.id));
    };

    return (
        <div className="card p-0 overflow-hidden">
            <div className="px-4 py-3 flex items-center gap-2">
                <Flag className="w-4 h-4 text-text-tertiary" />
                <span className="text-xs font-medium text-text-primary uppercase tracking-wider">Milestones</span>
                <button
                    onClick={() => setAdding(true)}
                    className="ml-auto text-xs text-accent-primary hover:underline flex items-center gap-1"
                >
                    <Plus className="w-3.5 h-3.5" /> Add
                </button>
            </div>
            {error && <p className="px-4 pb-2 text-xs text-red-400">{error}</p>}
            {adding && <NewMilestoneForm onCreate={create} onCancel={() => setAdding(false)} />}
            {milestones.length === 0 && !adding && (
                <p className="px-4 pb-4 text-sm text-text-tertiary">
                    No milestones yet. Add the dates that matter — a launch, a demo, a deadline —
                    then link tasks to them from the task page to watch progress fill in.
                </p>
            )}
            {milestones.map((ms) => (
                <MilestoneRow key={ms.id} milestone={ms} onUpdate={update} onDelete={remove} />
            ))}
        </div>
    );
}
