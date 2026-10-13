import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { ROUTES } from '../routes';
import { Bug, CheckSquare, Zap } from 'lucide-react';
import { TASK_TEMPLATES, DOD_TEMPLATES, getTaskTemplate, getDodTemplate } from '../lib/taskTemplates';

const TYPES = [
    { id: 'task', label: 'Task', Icon: CheckSquare, color: 'var(--accent-primary)' },
    { id: 'bug', label: 'Bug', Icon: Bug, color: '#e74c3c' },
    { id: 'epic', label: 'Epic', Icon: Zap, color: '#7c4dff' },
];
const BUG_TEMPLATE = 'What happened:\n\nExpected:\n\nSteps to reproduce:\n1. ';
const EPIC_COLORS = ['#7c4dff', '#00bcd4', '#2ecc71', '#f1c40f', '#e67e22', '#e74c3c', '#3498db', '#9b59b6'];

export function CreateTaskModal({ projectId, onClose, onCreated }) {
    const navigate = useNavigate();
    const [loading, setLoading] = useState(false);
    const [profiles, setProfiles] = useState([]);
    const [epics, setEpics] = useState([]);
    const [formData, setFormData] = useState({
        title: '',
        description: '',
        priority: 'medium',
        assignee: '',
        epic_id: '',
        tags: ''
    });
    const [type, setType] = useState('task');
    const [epicColor, setEpicColor] = useState(EPIC_COLORS[0]);
    const [dodItems, setDodItems] = useState([]);
    const [newDodText, setNewDodText] = useState('');
    const [files, setFiles] = useState([]);

    useEffect(() => {
        api.getProjectMembers(projectId).then(setProfiles).catch(console.error);
        api.getEpics(projectId).then(setEpics).catch(console.error);
    }, [projectId]);

    // Switching type keeps what was typed. A bug seeds a "what/expected/steps"
    // outline only into an empty description.
    const changeType = (next) => {
        setType(next);
        if (next === 'bug') {
            setFormData(prev => prev.description.trim() ? prev : { ...prev, description: BUG_TEMPLATE });
        }
    };

    const addDodItem = () => {
        if (!newDodText.trim()) return;
        setDodItems([...dodItems, { text: newDodText.trim(), checked: false }]);
        setNewDodText('');
    };

    const removeDodItem = (index) => setDodItems(dodItems.filter((_, i) => i !== index));

    // Task template: prefill the task's own fields. Fills empty fields only —
    // never clobbers what the user already typed. Does not touch the DoD.
    const applyTaskTemplate = (templateId) => {
        const tmpl = getTaskTemplate(templateId);
        if (!tmpl) return;
        setFormData(prev => {
            const next = { ...prev };
            if (tmpl.title && !prev.title.trim()) next.title = tmpl.title;
            if (tmpl.description && !prev.description.trim()) next.description = tmpl.description;
            if (tmpl.priority) next.priority = tmpl.priority;
            if (tmpl.tags?.length) {
                const have = prev.tags.split(',').map(t => t.trim()).filter(Boolean);
                next.tags = [...new Set([...have, ...tmpl.tags])].join(', ');
            }
            return next;
        });
    };

    // DoD template: toggle a named group of checklist items. Items carry the
    // template id so un-toggling removes exactly the items that group added.
    const isDodTemplateActive = (templateId) => dodItems.some(d => d.templateId === templateId);

    const toggleDodTemplate = (templateId) => {
        const tmpl = getDodTemplate(templateId);
        if (!tmpl) return;
        if (isDodTemplateActive(templateId)) {
            setDodItems(dodItems.filter(d => d.templateId !== templateId));
        } else {
            const added = tmpl.items.map(text => ({ text, checked: false, templateId }));
            setDodItems([...dodItems, ...added]);
        }
    };

    const addFiles = (fileList) => setFiles([...files, ...Array.from(fileList)]);

    const removeFile = (index) => setFiles(files.filter((_, i) => i !== index));

    const handleSubmit = async (e) => {
        e.preventDefault();
        setLoading(true);
        try {
            if (type === 'epic') {
                const epic = await api.createEpic(projectId, {
                    title: formData.title.trim(),
                    description: formData.description.trim(),
                    color: epicColor
                });
                if (onCreated) onCreated(epic);
                onClose();
                if (epic?.id) navigate(ROUTES.STUDIO_EPIC(epic.id));
                return;
            }
            const task = await api.createTask({
                project_id: projectId,
                ...formData,
                type,
                epic_id: formData.epic_id || undefined,
                tags: formData.tags.split(',').map(t => t.trim()).filter(Boolean),
                dod_items: dodItems.length ? dodItems.map(({ text, checked }) => ({ text, checked })) : undefined
            });
            for (const file of files) {
                await api.uploadAttachment(task.id, file);
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
    const chipStyle = { border: '1px solid var(--border-subtle)', color: 'var(--text-secondary)', backgroundColor: 'transparent' };

    return (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center animate-fade-in" onClick={onClose}>
            <form
                onSubmit={handleSubmit}
                className="w-full max-w-lg rounded-xl shadow-2xl overflow-hidden max-h-[90vh] flex flex-col"
                onClick={e => e.stopPropagation()}
                style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
            >
                <div className="flex items-center gap-2 px-4 py-3" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                    <h2 className="text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>New {type}</h2>
                    <div className="flex-1" />
                    <button type="button" aria-label="Close" onClick={onClose} className="btn btn-ghost px-2 py-0.5 text-base leading-none">×</button>
                </div>

                <div className="p-4 flex flex-col gap-4 overflow-y-auto">
                    <div role="radiogroup" aria-label="Type" className="grid grid-cols-3 gap-1 p-1 rounded-lg" style={{ backgroundColor: 'var(--bg-hover)' }}>
                        {TYPES.map(({ id, label, Icon, color }) => {
                            const active = type === id;
                            return (
                                <button
                                    key={id}
                                    type="button"
                                    role="radio"
                                    aria-checked={active}
                                    aria-label={label}
                                    onClick={() => changeType(id)}
                                    className="inline-flex items-center justify-center gap-1.5 py-1.5 rounded-md text-xs font-semibold transition-colors"
                                    style={active
                                        ? { backgroundColor: 'var(--bg-card)', color: 'var(--text-primary)', boxShadow: '0 1px 2px rgba(0,0,0,.2)' }
                                        : { color: 'var(--text-tertiary)' }}
                                >
                                    <Icon className="w-4 h-4" style={{ color: active ? color : undefined }} />
                                    {label}
                                </button>
                            );
                        })}
                    </div>

                    {type === 'task' && <div className="flex flex-wrap items-center gap-2">
                        <span className="text-[10px] font-bold uppercase" style={lbl}>Start from</span>
                        {TASK_TEMPLATES.map(t => (
                            <button
                                key={t.id}
                                type="button"
                                aria-label={`Task template: ${t.name}`}
                                onClick={() => applyTaskTemplate(t.id)}
                                className="px-2.5 py-1 rounded-md text-xs font-medium transition-colors"
                                style={chipStyle}
                            >
                                {t.name}
                            </button>
                        ))}
                    </div>}

                    <div>
                        <input
                            autoFocus
                            aria-label="Title"
                            className="input text-sm font-semibold"
                            placeholder={type === 'epic' ? 'What are we aiming for?' : `${type === 'bug' ? 'Bug' : 'Task'} title`}
                            value={formData.title}
                            onChange={e => setFormData({ ...formData, title: e.target.value })}
                            maxLength={255}
                            required
                        />
                        <textarea
                            aria-label="Description"
                            className="input resize-none h-24 mt-2"
                            placeholder="Add a description…"
                            value={formData.description}
                            onChange={e => setFormData({ ...formData, description: e.target.value })}
                        />
                    </div>

                    {type === 'epic' ? (
                        <div>
                            <label className={labelCls} style={lbl}>Colour</label>
                            <div className="flex flex-wrap gap-2.5">
                                {EPIC_COLORS.map(c => (
                                    <button
                                        key={c}
                                        type="button"
                                        aria-label={`Epic colour ${c}`}
                                        aria-pressed={epicColor === c}
                                        onClick={() => setEpicColor(c)}
                                        className={`w-7 h-7 rounded-full transition-transform hover:scale-110 ${epicColor === c ? 'ring-2 ring-white ring-offset-2 ring-offset-bg-card' : ''}`}
                                        style={{ backgroundColor: c }}
                                    />
                                ))}
                            </div>
                        </div>
                    ) : (<>
                    <div className="grid grid-cols-2 gap-3">
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
                            <label className={labelCls} style={lbl}>Assignee</label>
                            <select
                                aria-label="Assignee"
                                className="input"
                                value={formData.assignee}
                                onChange={e => setFormData({ ...formData, assignee: e.target.value })}
                            >
                                <option value="">Unassigned</option>
                                {profiles.map(p => (
                                    <option key={p.id} value={p.name}>
                                        {p.display_name || p.name} ({p.role})
                                    </option>
                                ))}
                            </select>
                        </div>
                        <div>
                            <label className={labelCls} style={lbl}>Tags</label>
                            <input
                                aria-label="Tags"
                                className="input"
                                placeholder="frontend, urgent"
                                value={formData.tags}
                                onChange={e => setFormData({ ...formData, tags: e.target.value })}
                            />
                        </div>
                    </div>

                    <div className="rounded-lg p-3" style={{ border: '1px solid var(--border-subtle)' }}>
                        <div className="flex flex-wrap items-center gap-2 mb-2">
                            <span className="text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>What "done" means</span>
                            <span className="text-[10px]" style={{ color: 'var(--text-tertiary)' }}>optional</span>
                            <div className="flex-1" />
                            {DOD_TEMPLATES.map(t => {
                                const active = isDodTemplateActive(t.id);
                                return (
                                    <button
                                        key={t.id}
                                        type="button"
                                        aria-label={`DoD template: ${t.name}`}
                                        aria-pressed={active}
                                        onClick={() => toggleDodTemplate(t.id)}
                                        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-colors"
                                        style={active
                                            ? { border: '1px solid var(--accent-primary)', color: 'var(--accent-on)', backgroundColor: 'var(--accent-primary)' }
                                            : chipStyle}
                                    >
                                        <span aria-hidden="true">{active ? '✓' : '+'}</span>
                                        {t.name}
                                    </button>
                                );
                            })}
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
                        <input
                            type="file"
                            multiple
                            className="text-sm"
                            style={{ color: 'var(--text-secondary)' }}
                            onChange={e => { addFiles(e.target.files); e.target.value = ''; }}
                        />
                    </div>
                    </>)}
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
