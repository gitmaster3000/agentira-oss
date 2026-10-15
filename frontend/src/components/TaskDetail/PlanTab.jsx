import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { UserAvatar } from '../UserAvatar';
import { ROUTES } from '../../routes';
import { AttachmentsSection } from './AttachmentsSection';
import { TestedBy } from './TestedBy';
import { LinksSection } from './LinksSection';
import { CollapsibleSection } from './CollapsibleSection';
import { BranchPrSection } from './BranchPrSection';
import { CommentsSection } from './ActivityFeed';
import { DescriptionEditor } from './TextDraft';
import { Markdown } from '../Markdown';
import {
    Clock,
    Calendar,
    CheckSquare,
    Square,
    Plus,
    X,
    Info,
    ListTree,
    Paperclip,
    Users,
} from 'lucide-react';

export const STATUS_OPTIONS = [
    { value: 'backlog', label: 'Backlog' },
    { value: 'todo', label: 'To Do' },
    { value: 'in_progress', label: 'In Progress' },
    { value: 'review', label: 'In Review' },
    { value: 'done', label: 'Done' },
];
const PRIORITY_OPTIONS = ['critical', 'high', 'medium', 'low'];

export const PlanTab = React.memo(function PlanTab(props) {
    const {
        task, isEditing, epics, saveField, formData, setFormData, profiles, priorityColors, dodItems, newDodText, setNewDodText,
        toggleDodItem, addDodItem, removeDodItem, projectRepos,
        commits, onDescriptionDraft,
        taskId, user, onComment, activities,
        loadTask,
    } = props;

    const assigneeName = isEditing ? formData.assignee : task.assignee;
    const [proofTick, setProofTick] = useState(0);
    const [openSections, setOpenSections] = useState({
        details: true, people: true, relations: true, dod: true, git: true, files: false, dates: true,
    });
    const toggleSection = (id) => setOpenSections(prev => ({ ...prev, [id]: !prev[id] }));

    return (
        <div className="space-y-6">
            {/* The top band is height-bounded so a long or short description
                never decides how much of the page is empty. The brief keeps its
                own pane; every other card shares one scrolling pane beside it.
                The page itself then scrolls once, to the discussion. */}
            <section
                aria-label="Task overview"
                data-testid="task-overview-section"
                className="grid grid-cols-1 xl:grid-cols-4 2xl:grid-cols-5 gap-4 xl:h-[62vh] xl:min-h-[26rem]"
            >
                {/* The card clips its own corners and the body scrolls inside
                    it, so long text never runs past the rounded edge. */}
                <div className="xl:col-span-2 min-w-0 xl:h-full flex flex-col bg-bg-card border border-border-subtle rounded-xl shadow-sm overflow-hidden">
                    <h3 className="text-xs font-bold uppercase text-text-tertiary px-5 pt-5 pb-3">Description</h3>
                    <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar px-5 pb-5">
                    {isEditing ? (
                        <DescriptionEditor
                            aria-label="Description"
                            className="w-full min-h-[10rem] h-full text-sm text-text-primary leading-relaxed bg-bg-app p-3 rounded-lg border border-border-subtle focus:outline-none focus:border-accent-primary resize-y"
                            initial={formData.description}
                            onDraft={onDescriptionDraft}
                            placeholder="Describe this task… (Markdown supported)"
                        />
                    ) : (
                        <div className="text-sm text-text-secondary leading-relaxed break-words overflow-x-auto">
                            {task.description
                                ? <Markdown>{task.description}</Markdown>
                                : <span className="italic text-text-tertiary">No description provided.</span>}
                        </div>
                    )}
                    </div>
                </div>

                {/* Everything else about the task lives in one panel of
                    collapsible sections — same shape as the side panel, so a
                    section reads the same wherever you meet it. */}
                <div className="xl:col-span-2 2xl:col-span-3 min-w-0 xl:h-full bg-bg-card border border-border-subtle rounded-xl shadow-sm overflow-hidden">
                {/* Sections stay a single vertical stack — the extra width goes
                    into spreading each section's own fields sideways, never into
                    a horizontal scrollbar. */}
                <div
                    data-testid="task-info-pane"
                    className="h-full overflow-y-auto overflow-x-hidden custom-scrollbar p-5"
                >

                <CollapsibleSection
                    title="Details"
                    icon={Info}
                    open={openSections.details}
                    onToggle={() => toggleSection('details')}
                >
                    <div className="grid grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4 gap-x-4 gap-y-4">
                        <div>
                            <label htmlFor="task-status" className="text-[10px] font-bold uppercase text-text-tertiary block mb-2">Status</label>
                            <select
                                id="task-status"
                                aria-label="Status"
                                className="ghost-select text-sm"
                                value={isEditing ? formData.status : task.status}
                                onChange={e => (isEditing
                                    ? setFormData({ ...formData, status: e.target.value })
                                    : saveField({ status: e.target.value }))}
                            >
                                {STATUS_OPTIONS.map(s => (
                                    <option key={s.value} value={s.value}>{s.label}</option>
                                ))}
                            </select>
                        </div>

                        <div>
                            <label htmlFor="task-priority" className="text-[10px] font-bold uppercase text-text-tertiary block mb-2">Priority</label>
                            <div className="flex items-center gap-2">
                                <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: priorityColors[isEditing ? formData.priority : task.priority] }} />
                                <select
                                    id="task-priority"
                                    aria-label="Priority"
                                    className="ghost-select text-sm capitalize"
                                    value={isEditing ? formData.priority : task.priority}
                                    onChange={e => (isEditing
                                        ? setFormData({ ...formData, priority: e.target.value })
                                        : saveField({ priority: e.target.value }))}
                                >
                                    {PRIORITY_OPTIONS.map(p => (
                                        <option key={p} value={p}>{p}</option>
                                    ))}
                                </select>
                            </div>
                        </div>

                        <div>
                            <label htmlFor="task-tags" className="text-[10px] font-bold uppercase text-text-tertiary block mb-2">Labels</label>
                            {isEditing ? (
                                <input
                                    id="task-tags"
                                    aria-label="Tags"
                                    className="ghost-select text-sm"
                                    placeholder="comma, separated, tags"
                                    value={(formData.tags || []).join(', ')}
                                    onChange={e => setFormData({
                                        ...formData,
                                        tags: e.target.value.split(',').map(t => t.trim()).filter(Boolean),
                                    })}
                                />
                            ) : (
                                <div className="flex flex-wrap gap-1.5">
                                    {(task.tags || []).length > 0 ? task.tags.map(t => (
                                        <span key={t} className="text-[10px] font-medium bg-bg-app px-2 py-0.5 rounded border border-border-subtle text-text-secondary">
                                            {t}
                                        </span>
                                    )) : <span className="text-xs text-text-tertiary italic">None</span>}
                                </div>
                            )}
                        </div>

                        <div>
                            <label htmlFor="task-epic" className="text-[10px] font-bold uppercase text-text-tertiary block mb-2">Epic</label>
                            <div className="flex items-center gap-2">
                                <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: task.epic_id ? (task.epic_color || '#7c4dff') : 'transparent' }} />
                                <select
                                    id="task-epic"
                                    aria-label="Epic"
                                    className="ghost-select text-sm"
                                    value={task.epic_id || ''}
                                    onChange={e => saveField({ epic_id: e.target.value })}
                                >
                                    <option value="">No epic</option>
                                    {epics.map(ep => <option key={ep.id} value={ep.id}>{ep.title}</option>)}
                                </select>
                            </div>
                            {task.epic_id && (
                                <Link to={ROUTES.STUDIO_EPIC(task.epic_id)} className="text-[10px] text-text-tertiary hover:underline mt-1 inline-block">
                                    Open epic
                                </Link>
                            )}
                        </div>

                        {projectRepos.length > 0 && (
                            <div className="col-span-full">
                                <label className="text-[10px] font-bold uppercase text-text-tertiary block mb-2">Repos</label>
                                <div className="flex flex-wrap gap-1.5">
                                    {(task.repos || []).length > 0
                                        ? task.repos.map(n => (
                                            <span key={n} className="text-[10px] font-medium bg-bg-app px-2 py-0.5 rounded border border-border-subtle text-text-secondary">{n}</span>
                                        ))
                                        : <span className="text-xs text-text-tertiary italic">none — falls back to project's primary repo</span>}
                                </div>
                            </div>
                        )}
                    </div>
                </CollapsibleSection>

                <CollapsibleSection
                    title="People"
                    icon={Users}
                    open={openSections.people}
                    onToggle={() => toggleSection('people')}
                    separated
                >
                    <div className="grid grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4 gap-x-4 gap-y-4">
                        <div>
                            <label htmlFor="task-assignee" className="text-[10px] font-bold uppercase text-text-tertiary block mb-2">Assignee</label>
                            <div className="flex items-center gap-2">
                            <div className="flex-shrink-0" data-testid="task-assignee-avatar">
                                <UserAvatar profile={profiles.find(p => p.name === assigneeName)} name={assigneeName || '?'} size={24} />
                            </div>
                            <select
                                id="task-assignee"
                                aria-label="Assignee"
                                className="ghost-select text-sm"
                                value={isEditing ? formData.assignee : (task.assignee || '')}
                                onChange={e => (isEditing
                                    ? setFormData({ ...formData, assignee: e.target.value })
                                    : saveField({ assignee: e.target.value }))}
                            >
                                <option value="">Unassigned</option>
                                {profiles.map(p => (
                                    <option key={p.id} value={p.name}>{p.display_name}</option>
                                ))}
                            </select>
                            </div>
                        </div>

                        <div>
                            <span className="text-[10px] font-bold uppercase text-text-tertiary block mb-2">Creator</span>
                            <div className="flex items-center gap-2" data-testid="task-creator">
                                <div className="w-6 h-6 rounded-full bg-accent-subtle flex items-center justify-center text-[10px] font-bold text-accent-primary flex-shrink-0">
                                    {task.creator ? task.creator[0].toUpperCase() : '?'}
                                </div>
                                <span className="text-sm text-text-secondary">{task.creator || 'Unknown'}</span>
                            </div>
                        </div>
                    </div>
                </CollapsibleSection>

                {/* Links to other tasks and the milestone this counts towards. */}
                <CollapsibleSection
                    title="Links"
                    icon={ListTree}
                    open={openSections.relations}
                    onToggle={() => toggleSection('relations')}
                    separated
                >
                    <LinksSection task={task} onChanged={loadTask} isEditing={isEditing} compact spread />
                </CollapsibleSection>

                <CollapsibleSection
                    title="Definition of Done"
                    icon={CheckSquare}
                    open={openSections.dod}
                    onToggle={() => toggleSection('dod')}
                    separated
                >
                    {dodItems.length > 0 && (
                        <div className="text-xs text-text-secondary mb-2">
                            {dodItems.filter(i => i.checked).length}/{dodItems.length} done
                        </div>
                    )}

                    {dodItems.length > 0 && (
                        <div className="w-full bg-bg-app rounded-full h-1.5 mb-3">
                            <div
                                className="h-1.5 rounded-full transition-all duration-300"
                                style={{
                                    width: `${dodItems.length ? (dodItems.filter(i => i.checked).length / dodItems.length) * 100 : 0}%`,
                                    backgroundColor: dodItems.every(i => i.checked) ? '#2ecc71' : '#7c4dff',
                                }}
                            />
                        </div>
                    )}

                    <div className="space-y-1">
                        {dodItems.map((item, i) => (
                            <div key={i} className="flex items-center gap-2 group py-1 px-2 rounded hover:bg-bg-hover transition-colors">
                                <button onClick={() => toggleDodItem(i)} className="flex-shrink-0 text-text-secondary hover:text-accent-primary transition-colors">
                                    {item.checked ? <CheckSquare className="w-4 h-4 text-green-500" /> : <Square className="w-4 h-4" />}
                                </button>
                                <span className={`text-sm flex-1 ${item.checked ? 'line-through text-text-tertiary' : 'text-text-primary'}`}>{item.text}</span>
                                <button onClick={() => removeDodItem(i)} className="opacity-0 group-hover:opacity-100 text-text-tertiary hover:text-red-400 transition-all p-0.5">
                                    <X className="w-3 h-3" />
                                </button>
                            </div>
                        ))}
                    </div>

                    <div className="flex items-center gap-2 mt-2">
                        <input
                            className="flex-1 bg-bg-app border border-border-subtle text-sm text-text-primary p-1.5 rounded focus:outline-none focus:border-accent-primary"
                            placeholder="Add DOD item..."
                            value={newDodText}
                            onChange={(e) => setNewDodText(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && addDodItem()}
                        />
                        <button onClick={addDodItem} className="p-1.5 rounded hover:bg-bg-hover text-text-tertiary hover:text-accent-primary transition-colors">
                            <Plus className="w-4 h-4" />
                        </button>
                    </div>

                    <div className="mt-3">
                        <TestedBy taskId={taskId} refreshKey={proofTick} />
                    </div>
                </CollapsibleSection>

                <BranchPrSection
                    task={task}
                    taskId={taskId}
                    commits={commits}
                    open={openSections.git}
                    onToggle={() => toggleSection('git')}
                    onSaved={loadTask}
                />

                <CollapsibleSection
                    title="Files"
                    icon={Paperclip}
                    open={openSections.files}
                    onToggle={() => toggleSection('files')}
                    separated
                >
                    <AttachmentsSection taskId={taskId} bare onChanged={() => setProofTick((t) => t + 1)} />
                </CollapsibleSection>

                <CollapsibleSection
                    title="Timestamps"
                    icon={Clock}
                    open={openSections.dates}
                    onToggle={() => toggleSection('dates')}
                    separated
                >
                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
                        <div className="flex items-center gap-2 text-text-secondary min-w-0">
                            <Calendar className="w-3.5 h-3.5 flex-shrink-0" />
                            <span className="text-xs flex-1">Due</span>
                            {isEditing ? (
                                <input
                                    type="date"
                                    aria-label="Due date"
                                    className="input input-date text-xs py-1 px-2 w-auto"
                                    value={formData.due_date || ''}
                                    onChange={e => setFormData({ ...formData, due_date: e.target.value })}
                                />
                            ) : (
                                <span className="text-xs" data-testid="task-due-date">
                                    {task.due_date
                                        ? new Date(task.due_date).toLocaleDateString()
                                        : 'Not set'}
                                </span>
                            )}
                        </div>
                        <div className="flex items-center gap-2 text-text-secondary min-w-0">
                            <Calendar className="w-3.5 h-3.5 flex-shrink-0" />
                            <span className="text-xs truncate">Created: {new Date(task.created_at).toLocaleDateString()}</span>
                        </div>
                        <div className="flex items-center gap-2 text-text-secondary min-w-0">
                            <Clock className="w-3.5 h-3.5 flex-shrink-0" />
                            <span className="text-xs truncate">Updated: {new Date(task.updated_at).toLocaleDateString()}</span>
                        </div>
                    </div>
                </CollapsibleSection>

                </div>
                </div>
            </section>

            <section
                aria-label="Discussion"
                data-testid="task-collaboration-section"
                className="border-t border-border-subtle pt-6"
            >
                <CommentsSection
                    user={user}
                    onComment={onComment}
                    activities={activities}
                    projectId={task.project_id}
                    members={profiles}
                />
            </section>
        </div>
    );
});
