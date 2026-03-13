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
    Pencil,
    CheckSquare,
    Square,
    Plus,
    GitCommit,
    GitPullRequest,
    GitBranch,
    ExternalLink,
    Copy,
    Check
} from 'lucide-react';
import { ConfirmModal } from './ConfirmModal';

function formatBranchDisplay(val) {
    if (!val) return '';
    // https://github.com/owner/repo/tree/branch-name → branch-name
    const treeMatch = val.match(/\/tree\/(.+)$/);
    if (treeMatch) return treeMatch[1];
    // strip protocol for other URLs
    if (val.startsWith('http')) return val.replace(/^https?:\/\/(www\.)?/, '');
    return val;
}

function formatPrDisplay(val) {
    if (!val) return '';
    // https://github.com/owner/repo/pull/5 → repo#5
    const prMatch = val.match(/github\.com\/[^/]+\/([^/]+)\/pull\/(\d+)/);
    if (prMatch) return `${prMatch[1]}#${prMatch[2]}`;
    if (val.startsWith('http')) return val.replace(/^https?:\/\/(www\.)?/, '');
    return val;
}
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
    const [commits, setCommits] = useState([]);
    const [dodItems, setDodItems] = useState(task.dod_items || []);
    const [newDodText, setNewDodText] = useState('');
    const [editingBranch, setEditingBranch] = useState(false);
    const [branchValue, setBranchValue] = useState(task.branch || '');
    const [editingPrUrl, setEditingPrUrl] = useState(false);
    const [prUrlValue, setPrUrlValue] = useState(task.pr_url || '');
    const [copiedField, setCopiedField] = useState(null);

    // Edit state
    const [isEditing, _setIsEditing] = useState(false);
    const setIsEditing = (v) => { _setIsEditing(v); onEditingChange?.(v); };
    const [formData, setFormData] = useState({ ...task });

    useEffect(() => {
        loadActivity();
        loadAttachments();
        loadCommits();
        setDodItems(task.dod_items || []);
        setBranchValue(task.branch || '');
        setPrUrlValue(task.pr_url || '');
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

    const loadCommits = async () => {
        try {
            const data = await api.listTaskCommits(task.id);
            if (Array.isArray(data)) setCommits(data);
        } catch (err) {
            // Git integration may not exist yet
        }
    };

    const saveBranch = async (val) => {
        setEditingBranch(false);
        if (val !== (task.branch || '')) {
            try {
                await api.updateTask(task.id, { branch: val });
                onUpdate();
            } catch (err) { console.error('Failed to save branch:', err); }
        }
    };

    const savePrUrl = async (val) => {
        setEditingPrUrl(false);
        if (val !== (task.pr_url || '')) {
            try {
                await api.updateTask(task.id, { pr_url: val });
                onUpdate();
            } catch (err) { console.error('Failed to save PR URL:', err); }
        }
    };

    const copyToClipboard = (text, field) => {
        navigator.clipboard.writeText(text);
        setCopiedField(field);
        setTimeout(() => setCopiedField(null), 800);
    };

    const toggleDodItem = async (index) => {
        const updated = dodItems.map((item, i) =>
            i === index ? { ...item, checked: !item.checked } : item
        );
        setDodItems(updated);
        try {
            await api.updateTask(task.id, { dod_items: updated });
            onUpdate();
        } catch (err) {
            console.error('Failed to update DOD:', err);
        }
    };

    const addDodItem = async () => {
        if (!newDodText.trim()) return;
        const updated = [...dodItems, { text: newDodText.trim(), checked: false }];
        setDodItems(updated);
        setNewDodText('');
        try {
            await api.updateTask(task.id, { dod_items: updated });
            onUpdate();
        } catch (err) {
            console.error('Failed to add DOD item:', err);
        }
    };

    const removeDodItem = async (index) => {
        const updated = dodItems.filter((_, i) => i !== index);
        setDodItems(updated);
        try {
            await api.updateTask(task.id, { dod_items: updated });
            onUpdate();
        } catch (err) {
            console.error('Failed to remove DOD item:', err);
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
                tags: typeof formData.tags === 'string' ? formData.tags.split(',').map(t => t.trim()) : formData.tags,
                branch: branchValue || undefined,
                pr_url: prUrlValue || undefined,
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
                className="absolute top-0 right-0 h-full w-[450px] bg-bg-card border-l border-border-subtle z-10 flex flex-col animate-slide-in shadow-elevation-3 overflow-hidden rounded-l-lg"
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
                            className="p-2 rounded-xl hover:bg-bg-hover text-text-secondary transition-colors"
                            title="Open in full page"
                        >
                            <Maximize2 className="w-4 h-4" />
                        </button>
                        <button
                            onClick={onClose}
                            className="p-2 rounded-xl hover:bg-bg-hover text-text-secondary transition-colors"
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
                                        className="bg-bg-app border border-border-subtle text-xl font-bold text-text-primary p-2 rounded-lg w-full focus:outline-none focus:border-accent-primary"
                                        value={formData.title}
                                        onChange={e => setFormData({ ...formData, title: e.target.value })}
                                        autoFocus
                                    />
                                ) : (
                                    <h1
                                        className="text-2xl font-bold text-text-primary p-1 -ml-1 rounded transition-colors cursor-pointer hover:bg-bg-hover"
                                        onClick={() => setIsEditing(true)}
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
                                    className="bg-bg-app border border-border-subtle text-sm text-text-primary p-3 rounded-lg w-full h-48 focus:outline-none focus:border-accent-primary resize-none"
                                    value={formData.description}
                                    onChange={e => setFormData({ ...formData, description: e.target.value })}
                                    placeholder="Add a more detailed description..."
                                />
                            ) : (
                                <div
                                    className="text-sm text-text-secondary leading-relaxed bg-bg-app/50 p-4 rounded-lg border border-border-subtle/30 min-h-[100px] cursor-pointer hover:border-border-subtle/60 transition-colors whitespace-pre-wrap break-words overflow-x-auto"
                                    onClick={() => setIsEditing(true)}
                                    style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}
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
                                            className="bg-bg-app border border-border-subtle text-xs text-text-primary p-1.5 rounded-lg w-full"
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
                                            className="bg-bg-app border border-border-subtle text-xs text-text-primary p-1.5 rounded-lg w-full"
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
                                            className="bg-bg-app border border-border-subtle text-xs text-text-primary p-1.5 rounded-lg w-full"
                                            value={Array.isArray(formData.tags) ? formData.tags.join(', ') : (formData.tags || '')}
                                            onChange={e => setFormData({ ...formData, tags: e.target.value })}
                                            placeholder="tag1, tag2..."
                                        />
                                    ) : (
                                        <div className="flex flex-wrap gap-1">
                                            {(task.tags || []).length > 0 ? task.tags.map(t => (
                                                <span key={t} className="text-[10px] bg-bg-panel px-2 py-0.5 rounded-md border border-border-subtle text-text-secondary">{t}</span>
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


                        {/* Definition of Done */}
                        <div className="mb-8">
                            <div className="flex items-center justify-between mb-3">
                                <label className="text-xs font-bold uppercase text-text-primary flex items-center gap-1.5">
                                    <CheckSquare className="w-3.5 h-3.5" /> Definition of Done
                                </label>
                                {dodItems.length > 0 && (
                                    <span className="text-xs text-text-tertiary">
                                        {dodItems.filter(i => i.checked).length}/{dodItems.length}
                                    </span>
                                )}
                            </div>

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
                                    <div key={i} className="flex items-center gap-2 group py-1 px-2 rounded-lg hover:bg-bg-hover transition-colors">
                                        <button onClick={() => toggleDodItem(i)} className="flex-shrink-0 text-text-secondary hover:text-accent-primary transition-colors">
                                            {item.checked
                                                ? <CheckSquare className="w-4 h-4 text-green-500" />
                                                : <Square className="w-4 h-4" />
                                            }
                                        </button>
                                        <span className={`text-sm flex-1 ${item.checked ? 'line-through text-text-tertiary' : 'text-text-primary'}`}>
                                            {item.text}
                                        </span>
                                        <button
                                            onClick={() => removeDodItem(i)}
                                            className="opacity-0 group-hover:opacity-100 text-text-tertiary hover:text-red-400 transition-all p-0.5"
                                        >
                                            <X className="w-3 h-3" />
                                        </button>
                                    </div>
                                ))}
                            </div>

                            <div className="flex items-center gap-2 mt-2">
                                <input
                                    className="flex-1 bg-bg-app border border-border-subtle text-sm text-text-primary p-1.5 rounded-lg focus:outline-none focus:border-accent-primary"
                                    placeholder="Add DOD item..."
                                    value={newDodText}
                                    onChange={(e) => setNewDodText(e.target.value)}
                                    onKeyDown={(e) => e.key === 'Enter' && addDodItem()}
                                />
                                <button onClick={addDodItem} className="p-1.5 rounded-lg hover:bg-bg-hover text-text-tertiary hover:text-accent-primary transition-colors">
                                    <Plus className="w-4 h-4" />
                                </button>
                            </div>
                        </div>

                        {/* Git Integration */}
                        <div className="mb-8">
                            <label className="text-xs font-bold uppercase text-text-primary flex items-center gap-1.5 mb-3">
                                <GitBranch className="w-3.5 h-3.5" /> Git
                            </label>

                            {/* Branch field */}
                            <div className="mb-3">
                                <div className="text-[10px] font-bold uppercase text-text-secondary mb-1">Branch</div>
                                {editingBranch ? (
                                    <input
                                        className="w-full px-2 py-1.5 text-sm bg-bg-app border border-border-subtle rounded-lg font-mono text-text-primary focus:outline-none focus:border-accent-primary"
                                        value={branchValue}
                                        onChange={e => setBranchValue(e.target.value)}
                                        onBlur={() => saveBranch(branchValue)}
                                        onKeyDown={e => e.key === 'Enter' && saveBranch(branchValue)}
                                        autoFocus
                                    />
                                ) : (
                                    <div className="flex items-center gap-1.5">
                                        {branchValue ? (
                                            <>
                                                {branchValue.startsWith('http') ? (
                                                    <a href={branchValue} target="_blank" rel="noopener noreferrer" className="text-sm font-mono text-accent-primary hover:underline truncate">
                                                        {formatBranchDisplay(branchValue)}
                                                    </a>
                                                ) : (
                                                    <span className="text-sm font-mono text-text-primary truncate">{branchValue}</span>
                                                )}
                                                <button onClick={() => setEditingBranch(true)} className="p-0.5 text-text-tertiary hover:text-text-secondary transition-colors flex-shrink-0" title="Edit">
                                                    <Pencil className="w-3 h-3" />
                                                </button>
                                                <button onClick={() => copyToClipboard(branchValue, 'branch')} className="p-0.5 text-text-tertiary hover:text-accent-primary transition-colors flex-shrink-0" title="Copy">
                                                    {copiedField === 'branch' ? <Check className="w-3 h-3 text-green-500" /> : <Copy className="w-3 h-3" />}
                                                </button>
                                            </>
                                        ) : (
                                            <span className="text-xs text-text-tertiary italic cursor-pointer hover:text-text-secondary" onClick={() => setEditingBranch(true)}>
                                                No branch set
                                            </span>
                                        )}
                                    </div>
                                )}
                            </div>

                            {/* PR URL field */}
                            <div className="mb-4">
                                <div className="text-[10px] font-bold uppercase text-text-secondary mb-1">Pull Request</div>
                                {editingPrUrl ? (
                                    <input
                                        className="w-full px-2 py-1.5 text-sm bg-bg-app border border-border-subtle rounded text-text-primary focus:outline-none focus:border-accent-primary"
                                        value={prUrlValue}
                                        onChange={e => setPrUrlValue(e.target.value)}
                                        onBlur={() => savePrUrl(prUrlValue)}
                                        onKeyDown={e => e.key === 'Enter' && savePrUrl(prUrlValue)}
                                        placeholder="https://github.com/..."
                                        autoFocus
                                    />
                                ) : (
                                    <div className="flex items-center gap-1.5">
                                        {prUrlValue ? (
                                            <>
                                                <a href={prUrlValue} target="_blank" rel="noopener noreferrer" className="text-sm text-accent-primary hover:underline truncate">
                                                    {formatPrDisplay(prUrlValue)}
                                                </a>
                                                <button onClick={() => setEditingPrUrl(true)} className="p-0.5 text-text-tertiary hover:text-text-secondary transition-colors flex-shrink-0" title="Edit">
                                                    <Pencil className="w-3 h-3" />
                                                </button>
                                                <button onClick={() => copyToClipboard(prUrlValue, 'pr')} className="p-0.5 text-text-tertiary hover:text-accent-primary transition-colors flex-shrink-0" title="Copy">
                                                    {copiedField === 'pr' ? <Check className="w-3 h-3 text-green-500" /> : <Copy className="w-3 h-3" />}
                                                </button>
                                            </>
                                        ) : (
                                            <span className="text-xs text-text-tertiary italic cursor-pointer hover:text-text-secondary" onClick={() => setEditingPrUrl(true)}>
                                                No PR linked
                                            </span>
                                        )}
                                    </div>
                                )}
                            </div>

                            {/* Read-only commit/PR list */}
                            {commits.length > 0 && (
                                <>
                                    <div className="text-[10px] font-bold uppercase text-text-secondary mb-1.5">
                                        Commits & PRs ({commits.length})
                                    </div>
                                    <div className="space-y-1.5">
                                        {commits.map((c) => (
                                            <div key={c.id} className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-bg-app border border-border-subtle/30 text-sm">
                                                {c.kind === 'pr'
                                                    ? <GitPullRequest className="w-3.5 h-3.5 text-purple-400 flex-shrink-0" />
                                                    : <GitCommit className="w-3.5 h-3.5 text-text-tertiary flex-shrink-0" />
                                                }
                                                <div className="flex-1 min-w-0">
                                                    <div className="text-text-primary truncate text-xs">
                                                        {c.kind === 'pr' ? `#${c.pr_number} ` : `${c.sha.slice(0, 7)} `}
                                                        {c.message}
                                                    </div>
                                                    <div className="text-[10px] text-text-tertiary">
                                                        {c.author}{c.branch ? ` on ${c.branch}` : ''}
                                                        {c.kind === 'pr' && c.pr_state && (
                                                            <span className={`ml-1.5 px-1 py-0.5 rounded text-[9px] font-medium ${
                                                                c.pr_state === 'merged' ? 'bg-purple-500/20 text-purple-400' :
                                                                c.pr_state === 'open' ? 'bg-green-500/20 text-green-400' :
                                                                'bg-red-500/20 text-red-400'
                                                            }`}>
                                                                {c.pr_state}
                                                            </span>
                                                        )}
                                                    </div>
                                                </div>
                                                {c.url && (
                                                    <a href={c.url} target="_blank" rel="noopener noreferrer" className="text-text-tertiary hover:text-accent-primary transition-colors flex-shrink-0">
                                                        <ExternalLink className="w-3 h-3" />
                                                    </a>
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                </>
                            )}
                        </div>

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
                                        className="w-full bg-bg-app border border-border-subtle text-sm p-3 rounded-lg focus:outline-none focus:border-accent-primary transition-colors"
                                        placeholder="Add a comment..."
                                        value={comment}
                                        onChange={e => setComment(e.target.value)}
                                    />
                                    <div className="mt-2 text-[10px] text-text-tertiary">
                                        Tip: Press <span className="p-0.5 bg-bg-panel border border-border-subtle rounded-md px-1">M</span> to focus comment box
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
                            className="flex items-center gap-2 text-xs text-red-400 hover:text-red-500 hover:bg-red-500/10 px-3 py-1.5 rounded-lg transition-all"
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
                                        setIsEditing(false);
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
                                onClick={() => setIsEditing(true)}
                                className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-text-primary hover:bg-bg-hover px-3 py-1.5 rounded-lg transition-all"
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
