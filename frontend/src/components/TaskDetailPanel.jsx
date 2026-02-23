import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../context/AuthContext';
import {
    Trash2,
    X,
    Maximize2,
    MessageSquare,
    Clock,
    User,
    Tag,
    AlertCircle,
    Pencil
} from 'lucide-react';
import { ConfirmModal } from './ConfirmModal';
import { AttachmentsSection } from './TaskDetail/AttachmentsSection';

export function TaskDetailPanel({ task, onClose, onUpdate, onEditingChange }) {
    const navigate = useNavigate();
    const { user } = useAuth();
    const [loading, setLoading] = useState(false);
    const [activities, setActivities] = useState([]);
    const [isConfirmingDelete, setIsConfirmingDelete] = useState(false);
    const [comment, setComment] = useState('');
    const [profiles, setProfiles] = useState([]);
    const [attachments, setAttachments] = useState([]);
    const [uploading, setUploading] = useState(false);

    // Edit state
    const [isEditing, setIsEditing] = useState(false);
    const [formData, setFormData] = useState({ ...task });

    // Notify parent of edit state changes
    const toggleEditing = (val) => {
        setIsEditing(val);
        if (onEditingChange) onEditingChange(val);
    };

    useEffect(() => {
        loadActivity();
        loadAttachments();
        if (task.project_id) {
            api.getProjectMembers(task.project_id).then(setProfiles).catch(console.error);
        }
        const interval = setInterval(loadActivity, 3000);
        return () => clearInterval(interval);
    }, [task.id]);

    const loadActivity = async () => {
        try {
            const data = await api.getActivity(task.id);
            setActivities(data);
        } catch (err) {
            console.error(err);
        }
    };

    const loadAttachments = async () => {
        try {
            const data = await api.listAttachments(task.id);
            if (Array.isArray(data)) setAttachments(data);
        } catch (err) {
            // Attachments endpoint may not exist yet — silently ignore
        }
    };

    const handleUpload = async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        setUploading(true);
        try {
            await api.uploadAttachment(task.id, file);
            loadAttachments();
            loadActivity();
        } catch (err) {
            alert(err.message);
        } finally {
            setUploading(false);
            e.target.value = '';
        }
    };

    const handleSave = async () => {
        setLoading(true);
        try {
            await api.updateTask(task.id, {
                title: formData.title,
                description: formData.description,
                priority: formData.priority,
                assignee: formData.assignee,
                tags: typeof formData.tags === 'string' ? formData.tags.split(',').map(t => t.trim()) : formData.tags
            });
            toggleEditing(false);
            onUpdate();
        } catch (err) {
            alert(err.message);
        } finally {
            setLoading(false);
        }
    };

    const handleComment = async (e) => {
        e.preventDefault();
        if (!comment.trim()) return;
        try {
            await api.addComment(task.id, { comment: comment });
            setComment('');
            loadActivity();
        } catch (err) {
            alert(err.message);
        }
    };

    const handleDelete = async () => {
        try {
            await api.deleteTask(task.id);
            onUpdate();
        } catch (err) {
            alert(err.message);
            setIsConfirmingDelete(false);
        }
    };

    const priorityColors = {
        critical: '#ef4444',
        high: '#f97316',
        medium: '#eab308',
        low: '#6b7280',
    };

    return (
        <>
            {/* Panel */}
            <div
                className="h-full w-[450px] bg-bg-card border-l border-border-subtle z-10 flex flex-col flex-shrink-0 animate-slide-in shadow-2xl overflow-hidden"
                onClick={e => e.stopPropagation()}
            >
                {/* Header */}
                <div className="h-14 flex items-center justify-between px-6 border-b border-border-subtle flex-shrink-0">
                    <div className="flex items-center gap-4 text-text-tertiary">
                        <span className="text-xs font-bold tracking-widest uppercase">Task Detail</span>
                        <div className="w-1 h-1 rounded-full bg-border-subtle" />
                        <span className="text-xs font-medium">#{task.id}</span>
                    </div>
                    <div className="flex items-center gap-1">
                        <button
                            onClick={() => navigate(`/tasks/${task.id}`)}
                            className="p-2 rounded-md hover:bg-bg-hover text-text-secondary transition-colors"
                            title="Open in full page"
                        >
                            <Maximize2 className="w-4 h-4" />
                        </button>
                        <button
                            onClick={onClose}
                            className="p-2 rounded-md hover:bg-bg-hover text-text-secondary transition-colors"
                        >
                            <X className="w-5 h-5" />
                        </button>
                    </div>
                </div>

                <div className="flex-1 overflow-y-auto custom-scrollbar">
                    <div className="p-8">
                        {/* Title */}
                        <div className="mb-8 flex items-start justify-between group">
                            <div className="flex-1 mr-4">
                                {isEditing ? (
                                    <input
                                        className="bg-bg-app border border-border-subtle text-xl font-bold text-text-primary p-2 rounded w-full focus:outline-none focus:border-accent-primary"
                                        value={formData.title}
                                        onChange={e => setFormData({ ...formData, title: e.target.value })}
                                        autoFocus
                                    />
                                ) : (
                                    <h1
                                        className="text-2xl font-bold text-text-primary p-1 -ml-1 rounded transition-colors cursor-pointer hover:bg-bg-hover"
                                        onClick={() => toggleEditing(true)}
                                    >
                                        {task.title}
                                    </h1>
                                )}
                            </div>
                        </div>

                        {/* Description */}
                        <div className="mb-8">
                            <div className="flex items-center justify-between mb-3 group/desc">
                                <label className="text-xs font-bold uppercase text-text-tertiary block">Description</label>
                            </div>
                            {isEditing ? (
                                <textarea
                                    className="bg-bg-app border border-border-subtle text-sm text-text-primary p-3 rounded w-full h-48 focus:outline-none focus:border-accent-primary resize-none"
                                    value={formData.description}
                                    onChange={e => setFormData({ ...formData, description: e.target.value })}
                                    placeholder="Add a more detailed description..."
                                />
                            ) : (
                                <div
                                    className="text-sm text-text-secondary leading-relaxed bg-bg-app/50 p-4 rounded border border-border-subtle/30 min-h-[100px] cursor-pointer hover:border-border-subtle/60 transition-colors"
                                    onClick={() => toggleEditing(true)}
                                >
                                    {task.description || "No description provided."}
                                </div>
                            )}
                        </div>

                        {/* Grid for properties */}
                        <div className="grid grid-cols-2 gap-x-12 gap-y-6 mb-8 border-t border-b border-border-subtle/30 py-8">
                            <div className="space-y-4">
                                <div>
                                    <label className="text-[10px] font-bold uppercase text-text-tertiary flex items-center gap-1.5 mb-2">
                                        <User className="w-3 h-3" /> Assignee
                                    </label>
                                    {isEditing ? (
                                        <select
                                            className="bg-bg-app border border-border-subtle text-xs text-text-primary p-1.5 rounded w-full"
                                            value={formData.assignee}
                                            onChange={e => setFormData({ ...formData, assignee: e.target.value })}
                                        >
                                            <option value="">Unassigned</option>
                                            {profiles.map(p => (
                                                <option key={p.id} value={p.name}>{p.display_name}</option>
                                            ))}
                                        </select>
                                    ) : (
                                        <div className="flex items-center gap-2">
                                            <div className="w-6 h-6 rounded-full bg-accent-subtle flex items-center justify-center text-[10px] font-bold text-accent-primary">
                                                {task.assignee ? task.assignee[0].toUpperCase() : '?'}
                                            </div>
                                            <span className="text-sm text-text-secondary">{task.assignee || 'Unassigned'}</span>
                                        </div>
                                    )}
                                </div>
                                <div>
                                    <label className="text-[10px] font-bold uppercase text-text-tertiary flex items-center gap-1.5 mb-2">
                                        <AlertCircle className="w-3 h-3" /> Priority
                                    </label>
                                    {isEditing ? (
                                        <select
                                            className="bg-bg-app border border-border-subtle text-xs text-text-primary p-1.5 rounded w-full"
                                            value={formData.priority}
                                            onChange={e => setFormData({ ...formData, priority: e.target.value })}
                                        >
                                            <option value="low">Low</option>
                                            <option value="medium">Medium</option>
                                            <option value="high">High</option>
                                            <option value="critical">Critical</option>
                                        </select>
                                    ) : (
                                        <div className="flex items-center gap-2">
                                            <div className="w-2 h-2 rounded-full" style={{ backgroundColor: priorityColors[task.priority] }} />
                                            <span className="text-sm text-text-secondary capitalize">{task.priority}</span>
                                        </div>
                                    )}
                                </div>
                            </div>
                            <div className="space-y-4">
                                <div>
                                    <label className="text-[10px] font-bold uppercase text-text-tertiary flex items-center gap-1.5 mb-2">
                                        <Tag className="w-3 h-3" /> Tags
                                    </label>
                                    {isEditing ? (
                                        <input
                                            className="bg-bg-app border border-border-subtle text-xs text-text-primary p-1.5 rounded w-full"
                                            value={Array.isArray(formData.tags) ? formData.tags.join(', ') : (formData.tags || '')}
                                            onChange={e => setFormData({ ...formData, tags: e.target.value })}
                                            placeholder="tag1, tag2..."
                                        />
                                    ) : (
                                        <div className="flex flex-wrap gap-1">
                                            {(task.tags || []).length > 0 ? task.tags.map(t => (
                                                <span key={t} className="text-[10px] bg-bg-panel px-2 py-0.5 rounded border border-border-subtle text-text-secondary">{t}</span>
                                            )) : <span className="text-xs text-text-tertiary italic">None</span>}
                                        </div>
                                    )}
                                </div>
                                <div>
                                    <label className="text-[10px] font-bold uppercase text-text-tertiary flex items-center gap-1.5 mb-2">
                                        <Clock className="w-3 h-3" /> Dates
                                    </label>
                                    <div className="space-y-1">
                                        <div className="text-[10px] text-text-tertiary">Created: {new Date(task.created_at).toLocaleDateString()}</div>
                                        <div className="text-[10px] text-text-tertiary">Updated: {new Date(task.updated_at).toLocaleDateString()}</div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* Action Buttons for Edit Mode */}
                        {isEditing && (
                            <div className="flex justify-end gap-2 mb-8">
                                <button onClick={() => { toggleEditing(false); setFormData({ ...task }); }} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary transition-colors">Cancel</button>
                                <button onClick={handleSave} className="bg-accent-primary text-white text-sm font-semibold px-6 py-2 rounded shadow-lg hover:bg-accent-hover transition-all" disabled={loading}>
                                    {loading ? 'Saving...' : 'Save Changes'}
                                </button>
                            </div>
                        )}

                        {/* Attachments Section */}
                        <div className="mb-8">
                            <AttachmentsSection taskId={task.id} />
                        </div>

                        {/* Comments / Activity Section */}
                        <div className="space-y-6">
                            <div className="flex items-center gap-2 text-text-primary mb-4">
                                <MessageSquare className="w-4 h-4" />
                                <h3 className="font-bold">Activity</h3>
                            </div>

                            {/* Comment Box */}
                            <div className="flex gap-4 mb-8">
                                <div className="w-8 h-8 rounded-full bg-accent-subtle flex items-center justify-center font-bold text-xs text-accent-primary flex-shrink-0">
                                    {user?.display_name?.[0]?.toUpperCase() || 'U'}
                                </div>
                                <form onSubmit={handleComment} className="flex-1">
                                    <input
                                        className="w-full bg-bg-app border border-border-subtle text-sm p-3 rounded-md focus:outline-none focus:border-accent-primary transition-colors"
                                        placeholder="Add a comment..."
                                        value={comment}
                                        onChange={e => setComment(e.target.value)}
                                    />
                                    <div className="mt-2 text-[10px] text-text-tertiary">
                                        Tip: Press <span className="p-0.5 bg-bg-panel border border-border-subtle rounded px-1">M</span> to focus comment box
                                    </div>
                                </form>
                            </div>

                            {/* Feed */}
                            <div className="space-y-6">
                                {activities.map((act, i) => (
                                    <div key={act.id} className="flex gap-4">
                                        <div className="w-8 h-8 rounded-full bg-bg-panel border border-border-subtle flex items-center justify-center font-bold text-xs text-text-tertiary flex-shrink-0">
                                            {act.actor?.[0]?.toUpperCase() || '?'}
                                        </div>
                                        <div className="flex-1">
                                            <div className="flex items-center gap-2 mb-1">
                                                <span className="text-sm font-bold text-text-primary">{act.actor}</span>
                                                <span className="text-xs text-text-tertiary">{new Date(act.created_at).toLocaleString()}</span>
                                            </div>
                                            <div className="text-sm text-text-secondary">
                                                <span className="text-accent-primary font-medium">{act.action}</span>: {act.detail}
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                </div>

                {/* Footer / Actions */}
                <div className="p-4 border-t border-border-subtle flex justify-between items-center bg-bg-panel/50">
                    <div>
                        <button
                            onClick={() => setIsConfirmingDelete(true)}
                            className="flex items-center gap-2 text-xs text-red-400 hover:text-red-500 hover:bg-red-500/10 px-3 py-1.5 rounded transition-all"
                            title="Delete Task"
                        >
                            <Trash2 className="w-4 h-4" /> Delete
                        </button>
                    </div>

                    <div className="flex items-center gap-2">
                        {isEditing ? (
                            <>
                                <button
                                    onClick={() => {
                                        setFormData(task);
                                        toggleEditing(false);
                                    }}
                                    className="btn btn-ghost text-xs py-1.5"
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={handleSave}
                                    disabled={loading}
                                    className="btn btn-primary text-xs py-1.5"
                                >
                                    {loading ? 'Saving...' : 'Save'}
                                </button>
                            </>
                        ) : (
                            <button
                                onClick={() => toggleEditing(true)}
                                className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-text-primary hover:bg-bg-hover px-3 py-1.5 rounded transition-all"
                                title="Edit Task"
                            >
                                <Pencil className="w-3.5 h-3.5" /> Edit
                            </button>
                        )}
                    </div>
                </div>
            </div>

            {isConfirmingDelete && (
                <ConfirmModal
                    title="Delete Task"
                    message={`Are you sure you want to delete task "${task.title}"? This action cannot be undone.`}
                    confirmText="Delete"
                    onConfirm={handleDelete}
                    onCancel={() => setIsConfirmingDelete(false)}
                />
            )}
        </>
    );
}
