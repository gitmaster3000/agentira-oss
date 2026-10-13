import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { ROUTES } from '../routes';

const TYPES = [
    { id: 'task', label: 'Task' },
    { id: 'bug', label: 'Bug' },
    { id: 'epic', label: 'Epic' },
];
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
    const [dodItems, setDodItems] = useState([]);
    const [newDodText, setNewDodText] = useState('');
    const [files, setFiles] = useState([]);

    useEffect(() => {
        api.getProjectMembers(projectId).then(setProfiles).catch(console.error);
        api.getEpics(projectId).then(setEpics).catch(console.error);
    }, [projectId]);

    const addDodItem = () => {
        if (!newDodText.trim()) return;
        setDodItems([...dodItems, { text: newDodText.trim(), checked: false }]);
        setNewDodText('');
    };

    const removeDodItem = (index) => setDodItems(dodItems.filter((_, i) => i !== index));

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
                        </div>
                    </div>

                    <div>
                        <label className={labelCls} style={lbl}>Description</label>
                        <textarea
                            aria-label="Description"
                            className="input resize-y h-56 min-h-[10rem]"
                            placeholder={type === 'epic' ? 'Goal, scope and what success looks like…' : 'Add a description…'}
                            value={formData.description}
                            onChange={e => setFormData({ ...formData, description: e.target.value })}
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
                                {profiles.map(p => (
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
                            <label className={labelCls} style={lbl}>Tags</label>
                            <input
                                aria-label="Tags"
                                className="input"
                                placeholder="frontend, urgent"
                                value={formData.tags}
                                onChange={e => setFormData({ ...formData, tags: e.target.value })}
                            />
                        </div>
                        </>)}
                    </div>

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
                        <input
                            type="file"
                            multiple
                            className="text-sm"
                            style={{ color: 'var(--text-secondary)' }}
                            onChange={e => { addFiles(e.target.files); e.target.value = ''; }}
                        />
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
