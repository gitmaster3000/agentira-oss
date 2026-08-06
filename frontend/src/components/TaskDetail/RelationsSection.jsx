import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ListTree, Ban, Flag, Plus, X, CornerDownRight } from 'lucide-react';
import { api } from '../../api';
import { ROUTES } from '../../routes';

/**
 * AP-496: how this task relates to the rest of the plan — its parent, its
 * subtasks, what it waits on, what waits on it, and which milestone it counts
 * towards. Labels stay plain ("waits on", not "blocked_by edge").
 */

const STATUS_COLORS = {
    done: '#2ecc71',
    review: '#ff9800',
    in_progress: '#7c4dff',
    todo: '#00bcd4',
    backlog: '#5f6368',
};

function TaskChip({ task, onOpen, onRemove, removeTitle }) {
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
                <button onClick={() => onRemove(task)} title={removeTitle}
                        className="text-text-tertiary hover:text-red-400 opacity-0 group-hover:opacity-100">
                    <X className="w-3 h-3" />
                </button>
            )}
        </div>
    );
}

function TaskPicker({ options, placeholder, onPick, onCancel }) {
    const [value, setValue] = useState('');
    return (
        <div className="flex items-center gap-2">
            <select
                autoFocus
                value={value}
                onChange={(e) => setValue(e.target.value)}
                className="flex-1 text-xs bg-bg-panel border border-border-subtle rounded px-2 py-1.5 text-text-primary"
            >
                <option value="">{placeholder}</option>
                {options.map(t => (
                    <option key={t.id} value={t.id}>{(t.key || t.id)} — {t.title}</option>
                ))}
            </select>
            <button disabled={!value} onClick={() => onPick(value)}
                    className="text-xs text-accent-primary disabled:opacity-40">Add</button>
            <button onClick={onCancel} className="text-text-tertiary hover:text-text-primary">
                <X className="w-3.5 h-3.5" />
            </button>
        </div>
    );
}

export function RelationsSection({ task, onChanged }) {
    const navigate = useNavigate();
    const projectId = task?.project_id;
    const [subtasks, setSubtasks] = useState([]);
    const [siblings, setSiblings] = useState([]);
    const [milestones, setMilestones] = useState([]);
    const [adding, setAdding] = useState(null);   // 'child' | 'waits' | 'blocks' | null
    const [error, setError] = useState(null);

    const load = useCallback(async () => {
        if (!task?.id || !projectId) return;
        try {
            const [children, projectTasks, ms] = await Promise.all([
                api.listSubtasks(task.id),
                api.listTasks(projectId),
                api.listMilestones(projectId),
            ]);
            setSubtasks(children || []);
            setSiblings((projectTasks || []).filter(t => t.id !== task.id));
            setMilestones(ms || []);
        } catch (err) {
            console.error('[RelationsSection] load failed:', err);
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

    const open = (id) => navigate(ROUTES.STUDIO_TASK(id));
    const addChild = (childId) => run(async () => {
        await api.updateTask(childId, { parent_id: task.id });
        setAdding(null);
    });
    const removeChild = (child) => run(() => api.updateTask(child.id, { parent_id: '' }));
    const addWaitsOn = (blockerId) => run(async () => {
        await api.addDependency(projectId, task.id, blockerId);
        setAdding(null);
    });
    const addBlocks = (dependentId) => run(async () => {
        await api.addDependency(projectId, dependentId, task.id);
        setAdding(null);
    });
    const removeLink = (other, direction) => run(async () => {
        const deps = await api.listDependencies(projectId);
        const match = deps.find(d => direction === 'waits'
            ? d.task_id === task.id && d.depends_on_id === other.id
            : d.task_id === other.id && d.depends_on_id === task.id);
        if (match) await api.removeDependency(projectId, match.id);
    });

    const waitingOn = task.blocked_by || [];
    const blocking = task.blocks || [];
    const parentId = task.parent_id;
    const parent = parentId ? siblings.find(t => t.id === parentId) : null;

    // Candidates exclude anything already linked in that direction — the
    // backend would reject a duplicate anyway; don't offer the dead end.
    const notLinked = (ids) => siblings.filter(t => !ids.includes(t.id));

    return (
        <div className="bg-bg-card border border-border-subtle rounded-xl p-6 shadow-sm space-y-5">
            <h3 className="text-xs font-bold uppercase text-text-secondary">How this fits in</h3>
            {error && <p className="text-xs text-red-400">{error}</p>}

            {/* Parent */}
            <div>
                <div className="text-[10px] font-bold uppercase text-text-secondary mb-1.5">Part of</div>
                {parent ? (
                    <TaskChip task={parent} onOpen={open}
                              onRemove={() => run(() => api.updateTask(task.id, { parent_id: '' }))}
                              removeTitle="Detach from parent" />
                ) : (
                    <select
                        value=""
                        onChange={(e) => e.target.value && run(
                            () => api.updateTask(task.id, { parent_id: e.target.value }))}
                        className="w-full text-xs bg-bg-panel border border-border-subtle rounded px-2 py-1.5 text-text-secondary"
                    >
                        <option value="">Not part of a bigger task</option>
                        {notLinked([task.id]).map(t => (
                            <option key={t.id} value={t.id}>{(t.key || t.id)} — {t.title}</option>
                        ))}
                    </select>
                )}
            </div>

            {/* Subtasks */}
            <div>
                <div className="flex items-center gap-2 mb-1.5">
                    <ListTree className="w-3.5 h-3.5 text-text-tertiary" />
                    <span className="text-[10px] font-bold uppercase text-text-secondary">
                        Subtasks {subtasks.length > 0 && `(${subtasks.filter(s => s.status === 'done').length}/${subtasks.length})`}
                    </span>
                    <button onClick={() => setAdding(adding === 'child' ? null : 'child')}
                            className="ml-auto text-text-tertiary hover:text-accent-primary" title="Add a subtask">
                        <Plus className="w-3.5 h-3.5" />
                    </button>
                </div>
                {adding === 'child' && (
                    <div className="mb-2">
                        <TaskPicker
                            options={notLinked(subtasks.map(s => s.id))}
                            placeholder="Pick a task to nest under this one"
                            onPick={addChild}
                            onCancel={() => setAdding(null)}
                        />
                    </div>
                )}
                <div className="space-y-1.5">
                    {subtasks.map(s => (
                        <div key={s.id} className="flex items-center gap-1">
                            <CornerDownRight className="w-3 h-3 text-text-tertiary flex-shrink-0" />
                            <div className="flex-1 min-w-0">
                                <TaskChip task={s} onOpen={open} onRemove={removeChild}
                                          removeTitle="Remove from this task" />
                            </div>
                        </div>
                    ))}
                    {subtasks.length === 0 && adding !== 'child' && (
                        <p className="text-xs text-text-tertiary">No subtasks yet.</p>
                    )}
                </div>
            </div>

            {/* Dependencies */}
            <div>
                <div className="flex items-center gap-2 mb-1.5">
                    <Ban className="w-3.5 h-3.5 text-text-tertiary" />
                    <span className="text-[10px] font-bold uppercase text-text-secondary">Waits on</span>
                    <button onClick={() => setAdding(adding === 'waits' ? null : 'waits')}
                            className="ml-auto text-text-tertiary hover:text-accent-primary"
                            title="Add something this task waits on">
                        <Plus className="w-3.5 h-3.5" />
                    </button>
                </div>
                {adding === 'waits' && (
                    <div className="mb-2">
                        <TaskPicker
                            options={notLinked(waitingOn.map(t => t.id))}
                            placeholder="This task can't start until…"
                            onPick={addWaitsOn}
                            onCancel={() => setAdding(null)}
                        />
                    </div>
                )}
                <div className="space-y-1.5">
                    {waitingOn.map(t => (
                        <TaskChip key={t.id} task={t} onOpen={open}
                                  onRemove={(other) => removeLink(other, 'waits')}
                                  removeTitle="Remove this link" />
                    ))}
                    {waitingOn.length === 0 && adding !== 'waits' && (
                        <p className="text-xs text-text-tertiary">Nothing — this can start any time.</p>
                    )}
                </div>
            </div>

            <div>
                <div className="flex items-center gap-2 mb-1.5">
                    <span className="text-[10px] font-bold uppercase text-text-secondary">Blocks</span>
                    <button onClick={() => setAdding(adding === 'blocks' ? null : 'blocks')}
                            className="ml-auto text-text-tertiary hover:text-accent-primary"
                            title="Add something waiting on this task">
                        <Plus className="w-3.5 h-3.5" />
                    </button>
                </div>
                {adding === 'blocks' && (
                    <div className="mb-2">
                        <TaskPicker
                            options={notLinked(blocking.map(t => t.id))}
                            placeholder="This task has to finish before…"
                            onPick={addBlocks}
                            onCancel={() => setAdding(null)}
                        />
                    </div>
                )}
                <div className="space-y-1.5">
                    {blocking.map(t => (
                        <TaskChip key={t.id} task={t} onOpen={open}
                                  onRemove={(other) => removeLink(other, 'blocks')}
                                  removeTitle="Remove this link" />
                    ))}
                    {blocking.length === 0 && adding !== 'blocks' && (
                        <p className="text-xs text-text-tertiary">Nothing is waiting on this.</p>
                    )}
                </div>
            </div>

            {/* Milestone */}
            <div>
                <div className="flex items-center gap-2 mb-1.5">
                    <Flag className="w-3.5 h-3.5 text-text-tertiary" />
                    <span className="text-[10px] font-bold uppercase text-text-secondary">Counts towards</span>
                </div>
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
            </div>
        </div>
    );
}
