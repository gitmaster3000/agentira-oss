import React, { useState, useRef, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { ROUTES } from '../routes';
import { LINK_TYPES } from './TaskDetail/LinksSection';
import { TitleEditor, DescriptionEditor } from './TaskDetail/TextDraft';

const TYPES = [
    { id: 'task', label: 'Task' },
    { id: 'bug', label: 'Bug' },
    { id: 'epic', label: 'Epic' },
];
const EPIC_COLORS = ['#7c4dff', '#00bcd4', '#2ecc71', '#f1c40f', '#e67e22', '#e74c3c', '#3498db', '#9b59b6'];

// `members`, `epics` and `projectName` come from the caller (ProjectLayout /
// TaskPage already hold them), so the dropdowns are filled on the first frame
// and opening the modal makes no request. Only the task list behind tag and
// link suggestions is fetched, on first use.
export function CreateTaskModal({ projectId, members = [], epics = [], projectName = '', onClose, onCreated }) {
    const navigate = useNavigate();
    const [loading, setLoading] = useState(false);
    // Title and description drafts live in their own inputs; Create reads them here.
    const draft = useRef({ title: '', description: '' });
    const [formData, setFormData] = useState({ priority: 'medium', assignee: '', epic_id: '', due_date: '' });
    const [tags, setTags] = useState([]);
    const [tagInput, setTagInput] = useState('');
    const [projectTasks, setProjectTasks] = useState([]);
    const tasksRequested = useRef(false);
    const [links, setLinks] = useState([]);
    const [linkType, setLinkType] = useState('relates_to');
    const [linkQuery, setLinkQuery] = useState('');
    const [dragging, setDragging] = useState(false);
    const [type, setType] = useState('task');
    const [dodItems, setDodItems] = useState([]);
    const [newDodText, setNewDodText] = useState('');
    const [files, setFiles] = useState([]);

    // First focus of the tag or link field loads the task list, once.
    const loadProjectTasks = () => {
        if (tasksRequested.current) return;
        tasksRequested.current = true;
        api.listTasks(projectId).then(r => setProjectTasks(r || [])).catch(console.error);
    };

    const addDodItem = () => {
        if (!newDodText.trim()) return;
        setDodItems([...dodItems, { text: newDodText.trim(), checked: false }]);
        setNewDodText('');
    };

    const removeDodItem = (index) => setDodItems(dodItems.filter((_, i) => i !== index));

    const addFiles = (fileList) => setFiles([...files, ...Array.from(fileList)]);

    const existingTags = useMemo(
        () => [...new Set(projectTasks.flatMap(t => t.tags || []))].sort(),
        [projectTasks],
    );
    const tagQuery = tagInput.trim().toLowerCase();
    const tagSuggestions = tagQuery
        ? existingTags.filter(t => t.toLowerCase().includes(tagQuery) && !tags.includes(t)).slice(0, 6)
        : [];

    const addTag = (raw) => {
        const t = raw.trim().replace(/,$/, '').trim();
        if (t && !tags.includes(t)) setTags([...tags, t]);
        setTagInput('');
    };

    const linkQ = linkQuery.trim().toLowerCase();
    const linkMatches = useMemo(() => (linkQ
        ? projectTasks
            .filter(t => !links.some(l => l.task.id === t.id)
                && `${t.key || t.id} ${t.title}`.toLowerCase().includes(linkQ))
            .slice(0, 6)
        : []), [projectTasks, links, linkQ]);

    const addLink = (task) => {
        setLinks([...links, { task, type: linkType }]);
        setLinkQuery('');
    };

    const removeFile = (index) => setFiles(files.filter((_, i) => i !== index));

    const handleSubmit = async (e) => {
        e.preventDefault();
        setLoading(true);
        try {
            if (type === 'epic') {
                const epic = await api.createEpic(projectId, {
                    title: draft.current.title.trim(),
                    description: draft.current.description.trim(),
                    assignee: formData.assignee,
                    color: EPIC_COLORS[epics.length % EPIC_COLORS.length]
                });
                for (const file of files) {
                    await api.uploadEpicAttachment(epic.id, file);
                }
                if (onCreated) onCreated(epic);
                onClose();
                if (epic?.id) navigate(ROUTES.STUDIO_EPIC(epic.id));
                return;
            }
            const task = await api.createTask({
                project_id: projectId,
                ...formData,
                ...draft.current,
                type,
                epic_id: formData.epic_id || undefined,
                due_date: formData.due_date || undefined,
                tags: tagInput.trim() && !tags.includes(tagInput.trim()) ? [...tags, tagInput.trim()] : tags,
                dod_items: dodItems.length ? dodItems.map(({ text, checked }) => ({ text, checked })) : undefined
            });
            for (const file of files) {
                await api.uploadAttachment(task.id, file);
            }
            for (const { task: other, type: linkKind } of links) {
                await api.addTaskLink(task.id, other.id, linkKind);
            }
            onCreated(task);
            onClose();
            if (task?.id) navigate(ROUTES.STUDIO_TASK(task.key || task.id));
        } catch (err) {
            alert(err.message);
        } finally {
            setLoading(false);
        }
    };

    const lbl = { color: 'var(--text-tertiary)', letterSpacing: '0.06em' };
    const labelCls = 'block text-[10px] font-bold uppercase mb-1.5';

    return (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center animate-fade-in" onClick={onClose}>
            <form
                onSubmit={handleSubmit}
                className="w-full max-w-2xl rounded-xl shadow-2xl overflow-hidden max-h-[90vh] flex flex-col"
                onClick={e => e.stopPropagation()}
                style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
            >
                <div className="flex items-center gap-2 px-4 py-3" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                    <h2 className="text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>New {type}</h2>
                    {projectName && <span className="text-xs" style={{ color: 'var(--text-muted)' }}>in {projectName}</span>}
                    <div className="flex-1" />
                    <button type="button" aria-label="Close" onClick={onClose} className="btn btn-ghost px-2 py-0.5 text-base leading-none">×</button>
                </div>

                <div className="p-4 flex flex-col gap-4 overflow-y-auto">
                    <div className="grid grid-cols-[8rem_1fr] gap-3">
                        <div>
                            <label className={labelCls} style={lbl}>Type</label>
                            <select
                                aria-label="Type"
                                className="input"
                                value={type}
                                onChange={e => setType(e.target.value)}
                            >
                                {TYPES.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}
                            </select>
                        </div>
                        <div>
                            <label className={labelCls} style={lbl}>Title</label>
                            <TitleEditor
                                autoFocus
                                aria-label="Title"
                                className="input text-sm font-semibold"
                                placeholder={type === 'epic' ? 'What are we aiming for?' : `${type === 'bug' ? 'Bug' : 'Task'} title`}
                                onDraft={v => { draft.current.title = v; }}
                                maxLength={255}
                                required
                            />
                        </div>
                    </div>

                    <div>
                        <label className={labelCls} style={lbl}>Description</label>
                        <DescriptionEditor
                            aria-label="Description"
                            className="input resize-y h-56 min-h-[10rem]"
                            placeholder={type === 'epic' ? 'Goal, scope and what success looks like…' : 'Add a description…'}
                            onDraft={v => { draft.current.description = v; }}
                        />
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                        <div>
                            <label className={labelCls} style={lbl}>Assignee</label>
                            <select
                                aria-label="Assignee"
                                className="input"
                                value={formData.assignee}
                                onChange={e => setFormData({ ...formData, assignee: e.target.value })}
                            >
                                <option value="">Unassigned</option>
                                {members.map(p => (
                                    <option key={p.id} value={p.name}>
                                        {p.display_name || p.name} ({p.role})
                                    </option>
                                ))}
                            </select>
                        </div>
                        {type !== 'epic' && (<>
                        <div>
                            <label className={labelCls} style={lbl}>Priority</label>
                            <select
                                aria-label="Priority"
                                className="input"
                                value={formData.priority}
                                onChange={e => setFormData({ ...formData, priority: e.target.value })}
                            >
                                <option value="low">Low</option>
                                <option value="medium">Medium</option>
                                <option value="high">High</option>
                                <option value="critical">Critical</option>
                            </select>
                        </div>
                        <div>
                            <label className={labelCls} style={lbl}>Epic</label>
                            <select
                                aria-label="Epic"
                                className="input"
                                value={formData.epic_id}
                                onChange={e => setFormData({ ...formData, epic_id: e.target.value })}
                            >
                                <option value="">No epic</option>
                                {epics.map(ep => (
                                    <option key={ep.id} value={ep.id}>{ep.title}</option>
                                ))}
                            </select>
                        </div>
                        <div>
                            <label className={labelCls} style={lbl}>Due date</label>
                            <input
                                type="date"
                                aria-label="Due date"
                                className="input"
                                value={formData.due_date}
                                onChange={e => setFormData({ ...formData, due_date: e.target.value })}
                            />
                        </div>
                        </>)}
                    </div>

                    {type !== 'epic' && (
                    <div>
                        <label className={labelCls} style={lbl}>Tags</label>
                        <div className="input flex flex-wrap items-center gap-1.5">
                            {tags.map(t => (
                                <span key={t} className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs" style={{ backgroundColor: 'var(--bg-hover, rgba(255,255,255,0.08))', color: 'var(--text-primary)' }}>
                                    {t}
                                    <button type="button" aria-label={`Remove tag ${t}`} onClick={() => setTags(tags.filter(x => x !== t))}>×</button>
                                </span>
                            ))}
                            <input
                                aria-label="Tags"
                                className="flex-1 min-w-[8rem] bg-transparent outline-none text-sm"
                                placeholder={tags.length ? '' : 'Type to add or find a tag'}
                                value={tagInput}
                                onChange={e => setTagInput(e.target.value)}
                                onFocus={loadProjectTasks}
                                onKeyDown={e => {
                                    if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); addTag(tagInput); }
                                    else if (e.key === 'Backspace' && !tagInput && tags.length) setTags(tags.slice(0, -1));
                                }}
                            />
                        </div>
                        {tagSuggestions.length > 0 && (
                            <div role="listbox" aria-label="Tag suggestions" className="mt-1 rounded-lg p-1" style={{ border: '1px solid var(--border-subtle)' }}>
                                {tagSuggestions.map(t => (
                                    <button key={t} type="button" role="option" onClick={() => addTag(t)}
                                            className="block w-full text-left text-sm px-2 py-1 rounded hover:bg-white/5"
                                            style={{ color: 'var(--text-primary)' }}>{t}</button>
                                ))}
                            </div>
                        )}
                    </div>
                    )}

                    {type !== 'epic' && (
                    <div className="rounded-lg p-3" style={{ border: '1px solid var(--border-subtle)' }}>
                        <span className="block text-xs font-semibold mb-2" style={{ color: 'var(--text-primary)' }}>Linked tasks</span>
                        {links.length > 0 && (
                            <div className="flex flex-col gap-1.5 mb-2">
                                {links.map((l, i) => (
                                    <div key={l.task.id} className="flex items-center gap-2 text-sm" style={{ color: 'var(--text-primary)' }}>
                                        <span className="text-[10px] uppercase" style={{ color: 'var(--text-tertiary)' }}>
                                            {LINK_TYPES.find(x => x.value === l.type)?.label}
                                        </span>
                                        <span className="text-[10px] font-mono" style={{ color: 'var(--text-tertiary)' }}>{l.task.key || l.task.id}</span>
                                        <span className="flex-1 truncate">{l.task.title}</span>
                                        <button type="button" onClick={() => setLinks(links.filter((_, j) => j !== i))} className="btn btn-ghost px-2 py-0.5 text-xs">Remove</button>
                                    </div>
                                ))}
                            </div>
                        )}
                        <div className="flex gap-2">
                            <select aria-label="Link type" className="input w-36" value={linkType} onChange={e => setLinkType(e.target.value)}>
                                {LINK_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                            </select>
                            <input
                                aria-label="Link task"
                                className="input flex-1"
                                placeholder="Search tasks by key or title…"
                                value={linkQuery}
                                onChange={e => setLinkQuery(e.target.value)}
                                onFocus={loadProjectTasks}
                            />
                        </div>
                        {linkMatches.length > 0 && (
                            <div role="listbox" aria-label="Task matches" className="mt-1 rounded-lg p-1" style={{ border: '1px solid var(--border-subtle)' }}>
                                {linkMatches.map(t => (
                                    <button key={t.id} type="button" role="option" onClick={() => addLink(t)}
                                            className="block w-full text-left text-sm px-2 py-1 rounded hover:bg-white/5 truncate"
                                            style={{ color: 'var(--text-primary)' }}>
                                        <span className="font-mono text-[10px] mr-2" style={{ color: 'var(--text-tertiary)' }}>{t.key || t.id}</span>{t.title}
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>
                    )}

                    {type !== 'epic' && (
                    <div className="rounded-lg p-3" style={{ border: '1px solid var(--border-subtle)' }}>
                        <div className="flex flex-wrap items-center gap-2 mb-2">
                            <span className="text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>Definition of Done</span>
                            <span className="text-[10px]" style={{ color: 'var(--text-tertiary)' }}>optional</span>
                        </div>
                        {dodItems.length > 0 && (
                            <div className="flex flex-col gap-1.5 mb-2">
                                {dodItems.map((item, i) => (
                                    <div key={i} className="flex items-center gap-2 text-sm" style={{ color: 'var(--text-primary)' }}>
                                        <span className="flex-1">{item.text}</span>
                                        <button type="button" onClick={() => removeDodItem(i)} className="btn btn-ghost px-2 py-0.5 text-xs">Remove</button>
                                    </div>
                                ))}
                            </div>
                        )}
                        <div className="flex gap-2">
                            <input
                                className="input flex-1"
                                placeholder="Add criterion…"
                                value={newDodText}
                                onChange={e => setNewDodText(e.target.value)}
                                onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addDodItem(); } }}
                            />
                            <button type="button" onClick={addDodItem} className="btn btn-ghost">Add</button>
                        </div>
                    </div>
                    )}

                    <div>
                        <label className={labelCls} style={lbl}>Attachments</label>
                        {files.length > 0 && (
                            <div className="flex flex-col gap-1.5 mb-2">
                                {files.map((file, i) => (
                                    <div key={i} className="flex items-center gap-2 text-sm" style={{ color: 'var(--text-primary)' }}>
                                        <span className="flex-1 truncate">{file.name}</span>
                                        <button type="button" onClick={() => removeFile(i)} className="btn btn-ghost px-2 py-0.5 text-xs">Remove</button>
                                    </div>
                                ))}
                            </div>
                        )}
                        <label
                            data-testid="dropzone"
                            className="block rounded-lg px-4 py-5 text-center text-sm cursor-pointer"
                            style={{
                                border: `1.5px dashed ${dragging ? 'var(--accent-primary, #c9b8ff)' : 'var(--border-subtle)'}`,
                                color: 'var(--text-secondary)',
                                backgroundColor: dragging ? 'rgba(201,184,255,0.08)' : 'transparent',
                            }}
                            onDragOver={e => { e.preventDefault(); setDragging(true); }}
                            onDragLeave={() => setDragging(false)}
                            onDrop={e => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files); }}
                        >
                            Drag &amp; drop files here, or <u>browse</u>
                            <input
                                type="file"
                                multiple
                                aria-label="Attach files"
                                className="sr-only"
                                onChange={e => { addFiles(e.target.files); e.target.value = ''; }}
                            />
                        </label>
                    </div>
                </div>

                <div className="flex items-center justify-end gap-2 px-4 py-3" style={{ borderTop: '1px solid var(--border-subtle)' }}>
                    <button type="button" onClick={onClose} className="btn btn-ghost">Cancel</button>
                    <button type="submit" disabled={loading} className="btn btn-primary">
                        {loading ? 'Creating...' : 'Create'}
                    </button>
                </div>
            </form>
        </div>
    );
}
