import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Flag, Link2, Plus, X } from 'lucide-react';
import { api } from '../../api';
import { ROUTES } from '../../routes';

/**
 * AP-507: every relationship this task has, as links. A link is one fact seen
 * from both sides — setting "waits on" here shows up as "blocks" over there.
 * Anyone can add a link; removing one needs edit mode.
 */

const STATUS_COLORS = {
    done: '#2ecc71',
    review: '#ff9800',
    in_progress: '#7c4dff',
    todo: '#00bcd4',
    backlog: '#5f6368',
};

export const LINK_TYPES = [
    { value: 'child_of', label: 'Part of' },
    { value: 'parent_of', label: 'Subtasks' },
    { value: 'depends_on', label: 'Waits on' },
    { value: 'blocks', label: 'Blocks' },
    { value: 'relates_to', label: 'Related to' },
    { value: 'duplicates', label: 'Duplicates' },
    { value: 'duplicated_by', label: 'Duplicated by' },
];

const LABELS = Object.fromEntries(LINK_TYPES.map(t => [t.value, t.label]));

function TaskChip({ task, onOpen, onRemove }) {
    return (
        <div className="flex items-center gap-2 px-2.5 py-1.5 rounded bg-bg-app border border-border-subtle/30 text-sm group">
            <span className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                  style={{ backgroundColor: STATUS_COLORS[task.status] || STATUS_COLORS.backlog }} />
            <button onClick={() => onOpen(task.id)}
                    className="text-[10px] font-mono text-text-tertiary hover:text-accent-primary flex-shrink-0">
                {task.key || task.id}
            </button>
            <span className="text-xs text-text-primary flex-1 min-w-0 truncate">{task.title}</span>
            {onRemove && (
                <button onClick={onRemove} title="Remove this link"
                        className="text-text-tertiary hover:text-red-400 opacity-0 group-hover:opacity-100">
                    <X className="w-3 h-3" />
                </button>
            )}
        </div>
    );
}

function LinkPicker({ options, onAdd, onCancel }) {
    const [type, setType] = useState('relates_to');
    const [target, setTarget] = useState('');
    return (
        <div className="space-y-2 mb-3 p-2 rounded bg-bg-app border border-border-subtle/40">
            <select value={type} onChange={(e) => setType(e.target.value)}
                    aria-label="Link type"
                    className="w-full text-xs bg-bg-panel border border-border-subtle rounded px-2 py-1.5 text-text-primary">
                {LINK_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
            <select value={target} onChange={(e) => setTarget(e.target.value)}
                    aria-label="Task to link"
                    className="w-full text-xs bg-bg-panel border border-border-subtle rounded px-2 py-1.5 text-text-primary">
                <option value="">Pick a task…</option>
                {options.map(t => (
                    <option key={t.id} value={t.id}>{(t.key || t.id)} — {t.title}</option>
                ))}
            </select>
            <div className="flex items-center gap-2">
                <button disabled={!target} onClick={() => onAdd(target, type)}
                        className="text-xs text-accent-primary disabled:opacity-40">Add link</button>
                <button onClick={onCancel} className="text-xs text-text-tertiary hover:text-text-primary">
                    Cancel
                </button>
            </div>
        </div>
    );
}

export function LinksSection({ task, onChanged, isEditing = false, onOpenTask, compact = false, spread = false }) {
    const navigate = useNavigate();
    const projectId = task?.project_id;
    const [links, setLinks] = useState([]);
    const [siblings, setSiblings] = useState([]);
    const [milestones, setMilestones] = useState([]);
    const [adding, setAdding] = useState(false);
    const [error, setError] = useState(null);

    const load = useCallback(async () => {
        if (!task?.id || !projectId) return;
        try {
            const [rows, projectTasks, ms] = await Promise.all([
                api.listTaskLinks(task.id),
                api.listTasks(projectId),
                api.listMilestones(projectId),
            ]);
            setLinks(rows || []);
            setSiblings((projectTasks || []).filter(t => t.id !== task.id));
            setMilestones(ms || []);
        } catch (err) {
            console.error('[LinksSection] load failed:', err);
        }
    }, [task?.id, projectId]);

    useEffect(() => { load(); }, [load]);

    const run = async (fn) => {
        setError(null);
        try {
            await fn();
            await load();
            onChanged?.();
        } catch (err) {
            setError(err.message || 'That change was rejected.');
        }
    };

    const open = (id) => {
        if (onOpenTask) {
            onOpenTask(id);
            return;
        }
        navigate(ROUTES.STUDIO_TASK(id));
    };

    const addLink = (otherId, linkType) => run(async () => {
        await api.addTaskLink(task.id, otherId, linkType);
        setAdding(false);
    });
    const removeLink = (link) => run(() => api.removeTaskLink(task.id, link.id));

    const linked = new Set(links.map(l => l.task.id));
    const milestone = milestones.find(m => m.id === task.milestone_id);

    return (
        <div className={compact
            ? (spread ? 'grid grid-cols-1 lg:grid-cols-2 gap-x-6 gap-y-4 [&>*]:min-w-0' : 'space-y-4')
            : 'min-w-0 bg-bg-card border border-border-subtle rounded-xl p-5 shadow-sm space-y-4'}>
            {!compact && <h3 className="text-xs font-bold uppercase text-text-tertiary">Links</h3>}

            <div className={spread ? 'lg:col-span-2' : ''}>
                <div className="flex items-center gap-2 mb-1.5">
                    <Link2 className="w-3.5 h-3.5 text-text-tertiary" />
                    <span className="text-[10px] font-bold uppercase text-text-secondary">
                        {links.length} linked
                    </span>
                    <button onClick={() => setAdding(!adding)} title="Add a link"
                            className="ml-auto text-text-tertiary hover:text-accent-primary">
                        <Plus className="w-3.5 h-3.5" />
                    </button>
                </div>
                {error && <p className="text-xs text-red-400 mb-2">{error}</p>}
                {adding && (
                    <LinkPicker
                        options={siblings.filter(t => !linked.has(t.id))}
                        onAdd={addLink}
                        onCancel={() => setAdding(false)}
                    />
                )}
                {links.length === 0 && !adding && (
                    <p className="text-xs text-text-tertiary">
                        Nothing linked yet. Link this to the work it waits on, blocks or belongs to.
                    </p>
                )}
            </div>

            {LINK_TYPES.map(({ value, label }) => {
                const group = links.filter(l => l.type === value);
                if (!group.length) return null;
                return (
                    <div key={value}>
                        <div className="text-[10px] font-bold uppercase text-text-secondary mb-1.5">{label}</div>
                        <div className="space-y-1.5">
                            {group.map(link => (
                                <TaskChip key={link.id} task={link.task} onOpen={open}
                                          onRemove={isEditing ? () => removeLink(link) : undefined} />
                            ))}
                        </div>
                    </div>
                );
            })}

            <div>
                <div className="flex items-center gap-2 mb-1.5">
                    <Flag className="w-3.5 h-3.5 text-text-tertiary" />
                    <span className="text-[10px] font-bold uppercase text-text-secondary">Counts towards</span>
                </div>
                {isEditing ? (
                    <select
                        value={task.milestone_id || ''}
                        onChange={(e) => run(() => api.updateTask(task.id, { milestone_id: e.target.value }))}
                        className="w-full text-xs bg-bg-panel border border-border-subtle rounded px-2 py-1.5 text-text-secondary"
                    >
                        <option value="">No milestone</option>
                        {milestones.map(m => (
                            <option key={m.id} value={m.id}>
                                {m.title}{m.due_date ? ` · ${new Date(m.due_date).toLocaleDateString()}` : ''}
                            </option>
                        ))}
                    </select>
                ) : (
                    <p className="text-xs text-text-tertiary">
                        {milestone
                            ? `${milestone.title}${milestone.due_date ? ` · ${new Date(milestone.due_date).toLocaleDateString()}` : ''}`
                            : 'No milestone.'}
                    </p>
                )}
            </div>
        </div>
    );
}
