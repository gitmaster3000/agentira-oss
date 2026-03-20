import React, { useState, useEffect } from 'react';
import { api } from '../api';

export function CreateTaskModal({ projectId, onClose, onCreated }) {
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

    useEffect(() => {
        api.getProjectMembers(projectId).then(setProfiles).catch(console.error);
        api.getEpics(projectId).then(setEpics).catch(console.error);
    }, [projectId]);

    const handleSubmit = async (e) => {
        e.preventDefault();
        setLoading(true);
        try {
            await api.createTask({
                project_id: projectId,
                ...formData,
                epic_id: formData.epic_id || undefined,
                tags: formData.tags.split(',').map(t => t.trim()).filter(Boolean)
            });
            onCreated();
            onClose();
        } catch (err) {
            alert(err.message);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center animate-fade-in" onClick={onClose}>
            <div
                className="w-full max-w-md rounded-xl shadow-2xl overflow-hidden"
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
