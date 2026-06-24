import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { ROUTES } from '../routes';

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
            const task = await api.createTask({
                project_id: projectId,
                ...formData,
                epic_id: formData.epic_id || undefined,
                tags: formData.tags.split(',').map(t => t.trim()).filter(Boolean),
                dod_items: dodItems.length ? dodItems : undefined
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

    return (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center animate-fade-in" onClick={onClose}>
            <div
                className="w-full max-w-md rounded-xl shadow-2xl overflow-hidden max-h-[90vh] overflow-y-auto"
                onClick={e => e.stopPropagation()}
                style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
            >
                <div className="px-6 py-5" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                    <h2 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>New Task</h2>
                </div>

                <form onSubmit={handleSubmit} className="p-6 flex flex-col gap-4">
                    <div>
                        <label className="block text-xs font-bold uppercase mb-1.5" style={{ color: 'var(--text-tertiary)', letterSpacing: '0.04em' }}>Title</label>
                        <input
                            autoFocus
                            className="input"
                            value={formData.title}
                            onChange={e => setFormData({ ...formData, title: e.target.value })}
                            maxLength={255}
                            required
                        />
                    </div>

                    <div>
                        <label className="block text-xs font-bold uppercase mb-1.5" style={{ color: 'var(--text-tertiary)', letterSpacing: '0.04em' }}>Description</label>
                        <textarea
                            className="input resize-none h-24"
                            value={formData.description}
                            onChange={e => setFormData({ ...formData, description: e.target.value })}
                        />
                    </div>

                    <div className="flex gap-4">
                        <div className="flex-1">
                            <label className="block text-xs font-bold uppercase mb-1.5" style={{ color: 'var(--text-tertiary)', letterSpacing: '0.04em' }}>Priority</label>
                            <select
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
                        <div className="flex-1">
                            <label className="block text-xs font-bold uppercase mb-1.5" style={{ color: 'var(--text-tertiary)', letterSpacing: '0.04em' }}>Epic</label>
                            <select
                                className="input"
                                value={formData.epic_id}
                                onChange={e => setFormData({ ...formData, epic_id: e.target.value })}
                            >
                                <option value="">Unassigned</option>
                                {epics.map(ep => (
                                    <option key={ep.id} value={ep.id}>{ep.title}</option>
                                ))}
                            </select>
                        </div>
                        <div className="flex-1">
                            <label className="block text-xs font-bold uppercase mb-1.5" style={{ color: 'var(--text-tertiary)', letterSpacing: '0.04em' }}>Assignee</label>
                            <select
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
                    </div>

                    <div>
                        <label className="block text-xs font-bold uppercase mb-1.5" style={{ color: 'var(--text-tertiary)', letterSpacing: '0.04em' }}>Tags</label>
                        <input
                            className="input"
                            placeholder="Comma separated, e.g. frontend, urgent"
                            value={formData.tags}
                            onChange={e => setFormData({ ...formData, tags: e.target.value })}
                        />
                    </div>

                    <div>
                        <label className="block text-xs font-bold uppercase mb-1.5" style={{ color: 'var(--text-tertiary)', letterSpacing: '0.04em' }}>Definition of Done</label>
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
                                placeholder="Add DOD item..."
                                value={newDodText}
                                onChange={e => setNewDodText(e.target.value)}
                                onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addDodItem(); } }}
                            />
                            <button type="button" onClick={addDodItem} className="btn btn-ghost">Add</button>
                        </div>
                    </div>

                    <div>
                        <label className="block text-xs font-bold uppercase mb-1.5" style={{ color: 'var(--text-tertiary)', letterSpacing: '0.04em' }}>Attachments</label>
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

                    <div className="flex justify-end gap-2 pt-3" style={{ borderTop: '1px solid var(--border-subtle)' }}>
                        <button type="button" onClick={onClose} className="btn btn-ghost">Cancel</button>
                        <button type="submit" disabled={loading} className="btn btn-primary">
                            {loading ? 'Creating...' : 'Create Task'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}
