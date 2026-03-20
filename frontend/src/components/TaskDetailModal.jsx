import React, { useState, useEffect } from 'react';
import { api } from '../api';
import {
    Paperclip, Pencil, Trash2, X,
    GitBranch, GitCommit, GitPullRequest, ExternalLink, Copy, Check,
    CheckSquare, Square, Plus
} from 'lucide-react';

function formatBranchDisplay(val) {
    if (!val) return '';
    const treeMatch = val.match(/\/tree\/(.+)$/);
    if (treeMatch) return treeMatch[1];
    if (val.startsWith('http')) return val.replace(/^https?:\/\/(www\.)?/, '');
    return val;
}

function formatPrDisplay(val) {
    if (!val) return '';
    const prMatch = val.match(/github\.com\/[^/]+\/([^/]+)\/pull\/(\d+)/);
    if (prMatch) return `${prMatch[1]}#${prMatch[2]}`;
    if (val.startsWith('http')) return val.replace(/^https?:\/\/(www\.)?/, '');
    return val;
}

export function TaskDetailModal({ task, onClose, onUpdate }) {
    const [loading, setLoading] = useState(false);
    const [activities, setActivities] = useState([]);
    const [comment, setComment] = useState('');
    const [profiles, setProfiles] = useState([]);
    const [epics, setEpics] = useState([]);
    const [attachments, setAttachments] = useState([]);
    const [uploading, setUploading] = useState(false);
    const [commits, setCommits] = useState([]);
    const [dodItems, setDodItems] = useState(task.dod_items || []);
    const [newDodText, setNewDodText] = useState('');
    const [editingBranch, setEditingBranch] = useState(false);
    const [branchValue, setBranchValue] = useState(task.branch || '');
    const [editingPrUrl, setEditingPrUrl] = useState(false);
    const [prUrlValue, setPrUrlValue] = useState(task.pr_url || '');
    const [copiedField, setCopiedField] = useState(null);

    // Edit state
    const [isEditing, setIsEditing] = useState(false);
    const [formData, setFormData] = useState({ ...task });

    useEffect(() => {
        loadActivity();
        loadAttachments();
        loadCommits();
        setDodItems(task.dod_items || []);
        setBranchValue(task.branch || '');
        setPrUrlValue(task.pr_url || '');
        api.getProjectMembers(task.project_id).then(setProfiles).catch(console.error);
        api.getEpics(task.project_id).then(setEpics).catch(console.error);
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
            setAttachments(data);
        } catch (err) {
            console.error(err);
        }
    };

    const loadCommits = async () => {
        try {
            const data = await api.listTaskCommits(task.id);
            if (Array.isArray(data)) setCommits(data);
        } catch (err) {}
    };

    const copyToClipboard = (text, field) => {
        navigator.clipboard.writeText(text);
        setCopiedField(field);
        setTimeout(() => setCopiedField(null), 800);
    };

    const saveBranch = async (val) => {
        setEditingBranch(false);
        if (val !== (task.branch || '')) {
            await api.updateTask(task.id, { branch: val });
            onUpdate();
        }
    };

    const savePrUrl = async (val) => {
        setEditingPrUrl(false);
        if (val !== (task.pr_url || '')) {
            await api.updateTask(task.id, { pr_url: val });
            onUpdate();
        }
    };

    const toggleDodItem = async (index) => {
        const updated = dodItems.map((item, i) => i === index ? { ...item, checked: !item.checked } : item);
        setDodItems(updated);
        await api.updateTask(task.id, { dod_items: updated });
        onUpdate();
    };

    const addDodItem = async () => {
        if (!newDodText.trim()) return;
        const updated = [...dodItems, { text: newDodText.trim(), checked: false }];
        setDodItems(updated);
        setNewDodText('');
        await api.updateTask(task.id, { dod_items: updated });
        onUpdate();
    };

    const removeDodItem = async (index) => {
        const updated = dodItems.filter((_, i) => i !== index);
        setDodItems(updated);
        await api.updateTask(task.id, { dod_items: updated });
        onUpdate();
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

    const handleDeleteAttachment = async (id, filename) => {
        if (!confirm(`Delete attachment "${filename}"?`)) return;
        try {
            await api.deleteAttachment(id);
            loadAttachments();
            loadActivity();
        } catch (err) {
            alert(err.message);
        }
    };

    const formatSize = (bytes) => {
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    };

    const handleSave = async () => {
        setLoading(true);
        try {
            await api.updateTask(task.id, {
                title: formData.title,
                description: formData.description,
                priority: formData.priority,
                assignee: formData.assignee,
                epic_id: formData.epic_id !== undefined ? formData.epic_id : undefined,
                tags: typeof formData.tags === 'string' ? formData.tags.split(',') : formData.tags
            });
            setIsEditing(false);
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
        if (!confirm("Delete this task?")) return;
        try {
            await api.deleteTask(task.id);
            onUpdate();
            onClose();
        } catch (err) {
            alert(err.message);
        }
    };

    const priorityColors = {
        critical: '#ef4444',
        high: '#f97316',
        medium: '#eab308',
        low: '#6b7280',
    };

    return (
        <div className="fixed inset-0 flex items-center justify-center p-4 z-50" style={{ backgroundColor: 'rgba(0,0,0,0.5)' }} onClick={onClose}>
            <div
                className="w-full max-w-3xl rounded-lg shadow-elevation-3 flex flex-col"
                onClick={e => e.stopPropagation()}
                style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border-subtle)', border: '1px solid var(--border-subtle)', maxHeight: '85vh' }}
            >
                {/* Header */}
                <div className="p-5 flex justify-between items-start" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                    <div className="flex-1">
                        {isEditing ? (
                            <input
                                className="input mb-2 font-bold text-lg"
                                value={formData.title}
                                onChange={e => setFormData({ ...formData, title: e.target.value })}
                            />
                        ) : (
                            <h2 className="text-xl font-bold cursor-pointer" onClick={() => setIsEditing(true)}>
                                {task.title}
                            </h2>
                        )}
                        <div className="flex gap-2 items-center mt-1 text-xs">
                            <span className="px-2 py-0.5 rounded-md" style={{
                                backgroundColor: task.status === 'done' ? 'rgba(46,204,113,0.15)' : 'var(--bg-panel)',
                                color: task.status === 'done' ? '#2ecc71' : 'var(--text-secondary)'
                            }}>
                                {task.status?.replace('_', ' ')}
                            </span>
                            <span className="px-2 py-0.5 rounded-md" style={{
                                backgroundColor: `${priorityColors[task.priority]}20`,
                                color: priorityColors[task.priority]
                            }}>
                                {task.priority}
                            </span>
                            <span style={{ color: 'var(--text-tertiary)' }}>#{task.id}</span>
                        </div>
                    </div>
                    <div className="flex items-center gap-1">
                        <button
                            onClick={() => setIsEditing(v => !v)}
                            className="p-2 rounded-xl hover:bg-bg-hover transition-colors"
                            style={{ color: isEditing ? 'var(--accent-primary)' : 'var(--text-secondary)' }}
                            title="Edit task"
                        >
                            <Pencil className="w-4 h-4" />
                        </button>
                        <button
                            onClick={handleDelete}
                            className="p-2 rounded-xl hover:bg-bg-hover transition-colors"
                            style={{ color: 'var(--text-secondary)' }}
                            title="Delete task"
                        >
                            <Trash2 className="w-4 h-4" />
                        </button>
                        <button onClick={onClose} className="p-2 rounded-xl hover:bg-bg-hover transition-colors" style={{ color: 'var(--text-secondary)' }}><X className="w-4 h-4" /></button>
                    </div>
                </div>

                <div className="flex-1 overflow-hidden flex" style={{ minHeight: 0 }}>
                    {/* Main Content */}
                    <div className="flex-1 p-5 overflow-y-auto" style={{ borderRight: '1px solid var(--border-subtle)' }}>
                        {/* Description */}
                        <div className="mb-5">
                            <label className="block text-xs font-semibold uppercase mb-2" style={{ color: 'var(--text-secondary)' }}>Description</label>
                            {isEditing ? (
                                <textarea
                                    className="input w-full h-32"
                                    value={formData.description}
                                    onChange={e => setFormData({ ...formData, description: e.target.value })}
                                    placeholder="Add a description..."
                                />
                            ) : (
                                <div
                                    className="text-sm cursor-pointer min-h-[3rem] rounded-lg p-2 whitespace-pre-wrap break-words overflow-x-auto"
                                    style={{ color: task.description ? 'var(--text-primary)' : 'var(--text-tertiary)', backgroundColor: 'var(--bg-panel)' }}
                                    onClick={() => setIsEditing(true)}
                                >
                                    {task.description || "Click to add description..."}
                                </div>
                            )}
                        </div>

                        {/* Fields grid */}
                        <div className="grid grid-cols-2 gap-4 mb-5">
                            <div>
                                <label className="block text-xs font-semibold uppercase mb-1" style={{ color: 'var(--text-secondary)' }}>Priority</label>
                                {isEditing ? (
                                    <select className="input" value={formData.priority} onChange={e => setFormData({ ...formData, priority: e.target.value })}>
                                        <option value="low">Low</option>
                                        <option value="medium">Medium</option>
                                        <option value="high">High</option>
                                        <option value="critical">Critical</option>
                                    </select>
                                ) : (
                                    <div className="text-sm capitalize" style={{ color: priorityColors[task.priority] }}>{task.priority}</div>
                                )}
                            </div>
                            <div>
                                <label className="block text-xs font-semibold uppercase mb-1" style={{ color: 'var(--text-secondary)' }}>Assignee</label>
                                {isEditing ? (
                                    <select className="input" value={formData.assignee} onChange={e => setFormData({ ...formData, assignee: e.target.value })}>
                                        <option value="">Unassigned</option>
                                        {profiles.map(p => (
                                            <option key={p.id} value={p.name}>{p.display_name} ({p.role})</option>
                                        ))}
                                    </select>
                                ) : (
                                    <div className="text-sm">{task.assignee || "Unassigned"}</div>
                                )}
                            </div>
                            <div>
                                <label className="block text-xs font-semibold uppercase mb-1" style={{ color: 'var(--text-secondary)' }}>Epic</label>
                                {isEditing ? (
                                    <select className="input" value={formData.epic_id || ""} onChange={e => setFormData({ ...formData, epic_id: e.target.value })}>
                                        <option value="">Unassigned</option>
                                        {epics.map(ep => (
                                            <option key={ep.id} value={ep.id}>{ep.title}</option>
                                        ))}
                                    </select>
                                ) : (
                                    <div className="flex items-center gap-2">
                                        {task.epic_name ? (
                                            <span 
                                                className="text-[10px] font-bold px-1.5 py-0.5 rounded-sm uppercase tracking-wider"
                                                style={{ backgroundColor: `${task.epic_color || '#7c4dff'}20`, color: task.epic_color || '#7c4dff' }}
                                            >
                                                {task.epic_name}
                                            </span>
                                        ) : (
                                            <span className="text-sm font-medium italic text-text-tertiary">None</span>
                                        )}
                                    </div>
                                )}
                            </div>
                            <div>
                                <label className="block text-xs font-semibold uppercase mb-1" style={{ color: 'var(--text-secondary)' }}>Tags</label>
                                {isEditing ? (
                                    <input
                                        className="input"
                                        value={Array.isArray(formData.tags) ? formData.tags.join(', ') : formData.tags}
                                        onChange={e => setFormData({ ...formData, tags: e.target.value })}
                                        placeholder="comma-separated"
                                    />
                                ) : (
                                    <div className="flex gap-1 flex-wrap">
                                        {(task.tags || []).length > 0 ? task.tags.map((t, i) => (
                                            <span key={i} className="text-xs px-2 py-0.5 rounded-md" style={{ backgroundColor: 'var(--accent-subtle)', color: 'var(--accent-primary)' }}>{t}</span>
                                        )) : <span className="text-xs" style={{ color: 'var(--text-tertiary)' }}>No tags</span>}
                                    </div>
                                )}
                            </div>
                            <div>
                                <label className="block text-xs font-semibold uppercase mb-1" style={{ color: 'var(--text-secondary)' }}>Created</label>
                                <div className="text-xs" style={{ color: 'var(--text-secondary)' }}>{new Date(task.created_at).toLocaleString()}</div>
                                <label className="block text-xs font-semibold uppercase mb-1 mt-2" style={{ color: 'var(--text-secondary)' }}>Updated</label>
                                <div className="text-xs" style={{ color: 'var(--text-secondary)' }}>{new Date(task.updated_at).toLocaleString()}</div>
                            </div>
                        </div>

                        {isEditing && (
                            <div className="flex gap-2 pt-4" style={{ borderTop: '1px solid var(--border-subtle)' }}>
                                <button onClick={handleSave} className="btn btn-primary" disabled={loading}>Save Changes</button>
                                <button onClick={() => { setIsEditing(false); setFormData({ ...task }); }} className="btn btn-ghost">Cancel</button>
                            </div>
                        )}

                        {/* Definition of Done */}
                        <div className="mt-5 pt-4" style={{ borderTop: '1px solid var(--border-subtle)' }}>
                            <div className="flex items-center justify-between mb-3">
                                <label className="text-xs font-bold uppercase flex items-center gap-1.5" style={{ color: 'var(--text-primary)' }}>
                                    <CheckSquare className="w-3.5 h-3.5" /> Definition of Done
                                </label>
                                {dodItems.length > 0 && (
                                    <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                                        {dodItems.filter(i => i.checked).length}/{dodItems.length}
                                    </span>
                                )}
                            </div>
                            {dodItems.length > 0 && (
                                <div className="w-full rounded-full h-1.5 mb-3" style={{ backgroundColor: 'var(--bg-app)' }}>
                                    <div className="h-1.5 rounded-full transition-all duration-300" style={{
                                        width: `${(dodItems.filter(i => i.checked).length / dodItems.length) * 100}%`,
                                        backgroundColor: dodItems.every(i => i.checked) ? '#2ecc71' : '#7c4dff',
                                    }} />
                                </div>
                            )}
                            <div className="space-y-1">
                                {dodItems.map((item, i) => (
                                    <div key={i} className="flex items-center gap-2 group py-1 px-2 rounded-lg hover:bg-bg-hover transition-colors">
                                        <button onClick={() => toggleDodItem(i)} className="flex-shrink-0" style={{ color: 'var(--text-secondary)' }}>
                                            {item.checked ? <CheckSquare className="w-4 h-4 text-green-500" /> : <Square className="w-4 h-4" />}
                                        </button>
                                        <span className="text-sm flex-1" style={{ color: item.checked ? 'var(--text-tertiary)' : 'var(--text-primary)', textDecoration: item.checked ? 'line-through' : 'none' }}>{item.text}</span>
                                        <button onClick={() => removeDodItem(i)} className="opacity-0 group-hover:opacity-100 hover:text-red-400 transition-all p-0.5" style={{ color: 'var(--text-tertiary)' }}>
                                            <X className="w-3 h-3" />
                                        </button>
                                    </div>
                                ))}
                            </div>
                            <div className="flex items-center gap-2 mt-2">
                                <input className="flex-1 text-sm p-1.5 rounded-lg" style={{ backgroundColor: 'var(--bg-app)', border: '1px solid var(--border-subtle)', color: 'var(--text-primary)' }}
                                    placeholder="Add DOD item..." value={newDodText} onChange={(e) => setNewDodText(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && addDodItem()} />
                                <button onClick={addDodItem} className="p-1.5 rounded-lg hover:bg-bg-hover transition-colors" style={{ color: 'var(--text-tertiary)' }}>
                                    <Plus className="w-4 h-4" />
                                </button>
                            </div>
                        </div>

                        {/* Git Integration */}
                        <div className="mt-5 pt-4" style={{ borderTop: '1px solid var(--border-subtle)' }}>
                            <label className="text-xs font-bold uppercase flex items-center gap-1.5 mb-3" style={{ color: 'var(--text-primary)' }}>
                                <GitBranch className="w-3.5 h-3.5" /> Git
                            </label>
                            <div className="mb-3">
                                <div className="text-[10px] font-bold uppercase mb-1" style={{ color: 'var(--text-secondary)' }}>Branch</div>
                                {editingBranch ? (
                                    <input className="w-full px-2 py-1.5 text-sm font-mono rounded-lg" style={{ backgroundColor: 'var(--bg-app)', border: '1px solid var(--border-subtle)', color: 'var(--text-primary)' }}
                                        value={branchValue} onChange={e => setBranchValue(e.target.value)} onBlur={() => saveBranch(branchValue)} onKeyDown={e => e.key === 'Enter' && saveBranch(branchValue)} autoFocus />
                                ) : (
                                    <div className="flex items-center gap-1.5">
                                        {branchValue ? (
                                            <>
                                                {branchValue.startsWith('http') ? (
                                                    <a href={branchValue} target="_blank" rel="noopener noreferrer" className="text-sm font-mono truncate" style={{ color: 'var(--accent-primary)' }}>{formatBranchDisplay(branchValue)}</a>
                                                ) : (
                                                    <span className="text-sm font-mono truncate" style={{ color: 'var(--text-primary)' }}>{branchValue}</span>
                                                )}
                                                <button onClick={() => setEditingBranch(true)} className="p-0.5 transition-colors flex-shrink-0" style={{ color: 'var(--text-tertiary)' }} title="Edit"><Pencil className="w-3 h-3" /></button>
                                                <button onClick={() => copyToClipboard(branchValue, 'branch')} className="p-0.5 transition-colors flex-shrink-0" style={{ color: 'var(--text-tertiary)' }} title="Copy">{copiedField === 'branch' ? <Check className="w-3 h-3 text-green-500" /> : <Copy className="w-3 h-3" />}</button>
                                            </>
                                        ) : (
                                            <span className="text-xs italic cursor-pointer" style={{ color: 'var(--text-tertiary)' }} onClick={() => setEditingBranch(true)}>No branch set</span>
                                        )}
                                    </div>
                                )}
                            </div>
                            <div className="mb-3">
                                <div className="text-[10px] font-bold uppercase mb-1" style={{ color: 'var(--text-secondary)' }}>Pull Request</div>
                                {editingPrUrl ? (
                                    <input className="w-full px-2 py-1.5 text-sm rounded-lg" style={{ backgroundColor: 'var(--bg-app)', border: '1px solid var(--border-subtle)', color: 'var(--text-primary)' }}
                                        value={prUrlValue} onChange={e => setPrUrlValue(e.target.value)} onBlur={() => savePrUrl(prUrlValue)} onKeyDown={e => e.key === 'Enter' && savePrUrl(prUrlValue)} placeholder="https://github.com/..." autoFocus />
                                ) : (
                                    <div className="flex items-center gap-1.5">
                                        {prUrlValue ? (
                                            <>
                                                <a href={prUrlValue} target="_blank" rel="noopener noreferrer" className="text-sm truncate" style={{ color: 'var(--accent-primary)' }}>{formatPrDisplay(prUrlValue)}</a>
                                                <button onClick={() => setEditingPrUrl(true)} className="p-0.5 transition-colors flex-shrink-0" style={{ color: 'var(--text-tertiary)' }} title="Edit"><Pencil className="w-3 h-3" /></button>
                                                <button onClick={() => copyToClipboard(prUrlValue, 'pr')} className="p-0.5 transition-colors flex-shrink-0" style={{ color: 'var(--text-tertiary)' }} title="Copy">{copiedField === 'pr' ? <Check className="w-3 h-3 text-green-500" /> : <Copy className="w-3 h-3" />}</button>
                                            </>
                                        ) : (
                                            <span className="text-xs italic cursor-pointer" style={{ color: 'var(--text-tertiary)' }} onClick={() => setEditingPrUrl(true)}>No PR linked</span>
                                        )}
                                    </div>
                                )}
                            </div>
                            {commits.length > 0 && (
                                <>
                                    <div className="text-[10px] font-bold uppercase mb-1.5" style={{ color: 'var(--text-secondary)' }}>Commits & PRs ({commits.length})</div>
                                    <div className="space-y-1.5">
                                        {commits.map((c) => (
                                            <div key={c.id} className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-sm" style={{ backgroundColor: 'var(--bg-app)', border: '1px solid var(--border-subtle)' }}>
                                                {c.kind === 'pr' ? <GitPullRequest className="w-3.5 h-3.5 text-purple-400 flex-shrink-0" /> : <GitCommit className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--text-secondary)' }} />}
                                                <div className="flex-1 min-w-0">
                                                    <div className="truncate text-xs" style={{ color: 'var(--text-primary)' }}>{c.kind === 'pr' ? `#${c.pr_number} ` : `${c.sha.slice(0, 7)} `}{c.message}</div>
                                                    <div className="text-[10px]" style={{ color: 'var(--text-secondary)' }}>{c.author}{c.branch ? ` on ${c.branch}` : ''}</div>
                                                </div>
                                                {c.url && <a href={c.url} target="_blank" rel="noopener noreferrer" className="flex-shrink-0" style={{ color: 'var(--text-tertiary)' }}><ExternalLink className="w-3 h-3" /></a>}
                                            </div>
                                        ))}
                                    </div>
                                </>
                            )}
                        </div>

                        {/* Attachments */}
                        <div className="mt-5 pt-4" style={{ borderTop: '1px solid var(--border-subtle)' }}>
                            <div className="flex items-center justify-between mb-3">
                                <label className="block text-xs font-semibold uppercase" style={{ color: 'var(--text-secondary)' }}>Attachments ({attachments.length})</label>
                                <label className="text-xs font-semibold px-3 py-1 rounded-lg cursor-pointer" style={{ backgroundColor: 'var(--accent-subtle)', color: 'var(--accent-primary)' }}>
                                    {uploading ? 'Uploading…' : '+ Upload'}
                                    <input type="file" className="hidden" onChange={handleUpload} disabled={uploading} />
                                </label>
                            </div>
                            {attachments.length === 0 ? (
                                <div className="text-xs py-3 text-center rounded-lg" style={{ color: 'var(--text-tertiary)', backgroundColor: 'var(--bg-panel)' }}>
                                    No attachments yet
                                </div>
                            ) : (
                                <div className="space-y-2">
                                    {attachments.map(att => (
                                        <div key={att.id} className="flex items-center gap-3 p-2 rounded-lg text-sm" style={{ backgroundColor: 'var(--bg-panel)' }}>
                                            <Paperclip className="w-4 h-4 flex-shrink-0" style={{ color: 'var(--text-secondary)' }} />
                                            <div className="flex-1 min-w-0">
                                                <a
                                                    href={api.getAttachmentDownloadUrl(att.id)}
                                                    target="_blank"
                                                    rel="noopener noreferrer"
                                                    className="text-sm font-medium truncate block"
                                                    style={{ color: 'var(--accent-primary)' }}
                                                >
                                                    {att.filename}
                                                </a>
                                                <div className="text-xs" style={{ color: 'var(--text-tertiary)' }}>
                                                    {formatSize(att.size_bytes)} · {att.uploaded_by} · {new Date(att.created_at).toLocaleDateString()}
                                                </div>
                                            </div>
                                            <button
                                                onClick={() => handleDeleteAttachment(att.id, att.filename)}
                                                className="p-1 rounded-lg text-xs"
                                                style={{ color: 'var(--text-tertiary)' }}
                                                title="Delete"
                                            >
                                                <Trash2 className="w-3.5 h-3.5" />
                                            </button>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>

                    {/* Sidebar / Activity */}
                    <div className="w-80 flex flex-col" style={{ backgroundColor: 'var(--bg-panel)' }}>
                        <div className="p-4 font-semibold text-sm" style={{ borderBottom: '1px solid var(--border-subtle)' }}>Activity</div>

                        <div className="flex-1 overflow-y-auto p-4 space-y-3">
                            {activities.map(act => (
                                <div key={act.id} className="text-sm">
                                    <div className="flex justify-between items-baseline mb-0.5">
                                        <span className="font-semibold text-xs">{act.actor}</span>
                                        <span className="text-xs" style={{ color: 'var(--text-tertiary)' }}>{new Date(act.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                                    </div>
                                    <div className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                                        <span style={{ color: 'var(--accent-primary)' }}>{act.action}</span>: {act.detail}
                                    </div>
                                </div>
                            ))}
                        </div>

                        <div className="p-4" style={{ borderTop: '1px solid var(--border-subtle)' }}>
                            <form onSubmit={handleComment}>
                                <input
                                    className="input text-sm"
                                    placeholder="Add a comment..."
                                    value={comment}
                                    onChange={e => setComment(e.target.value)}
                                />
                            </form>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
