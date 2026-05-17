import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../context/AuthContext';
import { Breadcrumbs } from '../components/Breadcrumbs';
import {
    ChevronLeft,
    Clock,
    User,
    Tag,
    AlertCircle,
    MessageSquare,
    Trash2,
    Calendar,
    GitBranch,
    GitCommit,
    GitPullRequest,
    ExternalLink,
    Copy,
    Check,
    Pencil,
    CheckSquare,
    Square,
    Plus,
    X
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

export function TaskPage() {
    const { taskId } = useParams();
    const navigate = useNavigate();
    const { user } = useAuth();
    const [task, setTask] = useState(null);
    const [activities, setActivities] = useState([]);
    const [comment, setComment] = useState('');
    const [profiles, setProfiles] = useState([]);
    const [loading, setLoading] = useState(true);
    const [commits, setCommits] = useState([]);
    const [dodItems, setDodItems] = useState([]);
    const [newDodText, setNewDodText] = useState('');
    const [editingBranch, setEditingBranch] = useState(false);
    const [branchValue, setBranchValue] = useState('');
    const [editingPrUrl, setEditingPrUrl] = useState(false);
    const [prUrlValue, setPrUrlValue] = useState('');
    const [copiedField, setCopiedField] = useState(null);

    const loadTask = async () => {
        try {
            const data = await api.getTask(taskId);
            setTask(data);
            setDodItems(data.dod_items || []);
            setBranchValue(data.branch || '');
            setPrUrlValue(data.pr_url || '');
        } catch (err) { console.error(err); }
    };

    const loadCommits = async () => {
        try {
            const data = await api.listTaskCommits(taskId);
            if (Array.isArray(data)) setCommits(data);
        } catch (err) {}
    };

    useEffect(() => {
        const load = async () => {
            try {
                const data = await api.getTask(taskId);
                setTask(data);
                setDodItems(data.dod_items || []);
                setBranchValue(data.branch || '');
                setPrUrlValue(data.pr_url || '');
                const actData = await api.getActivity(taskId);
                setActivities(actData);
                const profData = await api.getProjectMembers(data.project_id);
                setProfiles(profData);
                const commitData = await api.listTaskCommits(taskId);
                if (Array.isArray(commitData)) setCommits(commitData);
            } catch (err) {
                console.error(err);
            } finally {
                setLoading(false);
            }
        };
        load();
    }, [taskId]);

    const copyToClipboard = (text, field) => {
        navigator.clipboard.writeText(text);
        setCopiedField(field);
        setTimeout(() => setCopiedField(null), 800);
    };

    const saveBranch = async (val) => {
        setEditingBranch(false);
        if (task && val !== (task.branch || '')) {
            await api.updateTask(taskId, { branch: val });
            loadTask();
        }
    };

    const savePrUrl = async (val) => {
        setEditingPrUrl(false);
        if (task && val !== (task.pr_url || '')) {
            await api.updateTask(taskId, { pr_url: val });
            loadTask();
        }
    };

    const toggleDodItem = async (index) => {
        const updated = dodItems.map((item, i) => i === index ? { ...item, checked: !item.checked } : item);
        setDodItems(updated);
        await api.updateTask(taskId, { dod_items: updated });
    };

    const addDodItem = async () => {
        if (!newDodText.trim()) return;
        const updated = [...dodItems, { text: newDodText.trim(), checked: false }];
        setDodItems(updated);
        setNewDodText('');
        await api.updateTask(taskId, { dod_items: updated });
    };

    const removeDodItem = async (index) => {
        const updated = dodItems.filter((_, i) => i !== index);
        setDodItems(updated);
        await api.updateTask(taskId, { dod_items: updated });
    };

    const handleComment = async (e) => {
        e.preventDefault();
        if (!comment.trim()) return;
        try {
            await api.addComment(taskId, { comment });
            setComment('');
            const actData = await api.getActivity(taskId);
            setActivities(actData);
        } catch (err) {
            alert(err.message);
        }
    };

    if (loading) return <div className="p-8 text-text-secondary">Loading task...</div>;
    if (!task) return <div className="p-8 text-red-400">Task not found.</div>;

    const priorityColors = {
        critical: '#ef4444',
        high: '#f97316',
        medium: '#eab308',
        low: '#6b7280',
    };

    return (
        <div className="flex-1 bg-bg-app overflow-y-auto">
            <div className="max-w-7xl mx-auto p-8">
                <div className="mb-6">
                    <Breadcrumbs entity="task" data={task} />
                </div>

                <div className="flex flex-col lg:flex-row gap-12">
                    {/* Main Content */}
                    <div className="flex-1">
                        <h1 className="text-3xl font-bold text-text-primary mb-4">{task.title}</h1>

                        <div className="mb-10">
                            <h2 className="text-sm font-bold uppercase text-text-tertiary mb-3">Description</h2>
                            <div className="text-base text-text-secondary leading-relaxed bg-bg-card p-6 rounded-lg border border-border-subtle shadow-sm whitespace-pre-wrap">
                                {task.description || "No description provided."}
                            </div>
                        </div>

                        <div className="space-y-8">
                            <h2 className="text-sm font-bold uppercase text-text-tertiary border-b border-border-subtle pb-2 flex items-center gap-2">
                                <MessageSquare className="w-4 h-4" /> Activity
                            </h2>

                            {/* Comment Input */}
                            <div className="flex gap-4">
                                <div className="w-10 h-10 rounded-full bg-accent-subtle flex items-center justify-center font-bold text-sm text-accent-primary">
                                    {user?.display_name?.[0]?.toUpperCase() || 'U'}
                                </div>
                                <form onSubmit={handleComment} className="flex-1">
                                    <textarea
                                        className="w-full bg-bg-card border border-border-subtle text-sm p-4 rounded-lg focus:outline-none focus:border-accent-primary transition-colors h-24 resize-none shadow-sm"
                                        placeholder="Add a comment..."
                                        value={comment}
                                        onChange={e => setComment(e.target.value)}
                                    />
                                    <div className="mt-2 flex justify-end">
                                        <button className="btn btn-primary">Add Comment</button>
                                    </div>
                                </form>
                            </div>

                            {/* Activity Feed */}
                            <div className="space-y-8 mt-8">
                                {activities.map(act => (
                                    <div key={act.id} className="flex gap-4 group">
                                        <div className="w-10 h-10 rounded-full bg-bg-card border border-border-subtle flex items-center justify-center font-bold text-xs text-text-tertiary shadow-sm">
                                            {act.actor?.[0]?.toUpperCase() || '?'}
                                        </div>
                                        <div className="flex-1">
                                            <div className="flex items-center gap-3 mb-1">
                                                <span className="text-sm font-bold text-text-primary">{act.actor}</span>
                                                <span className="text-xs text-text-tertiary">
                                                    {new Date(act.created_at).toLocaleDateString()} at {new Date(act.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                                </span>
                                            </div>
                                            <div className="text-sm text-text-secondary">
                                                <span className="text-accent-primary font-medium mr-1">{act.action}</span>
                                                {act.detail}
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>

                    {/* Sidebar / Properties */}
                    <div className="w-full lg:w-80 space-y-8">
                        <div className="bg-bg-card border border-border-subtle rounded-xl p-6 shadow-sm">
                            <h3 className="text-xs font-bold uppercase text-text-tertiary mb-6 pb-2 border-b border-border-subtle/50">Details</h3>

                            <div className="space-y-6">
                                <div>
                                    <label className="text-[10px] font-bold uppercase text-text-tertiary block mb-2">Status</label>
                                    <span className={`text-xs px-2.5 py-1 rounded font-bold uppercase tracking-wider
                                        ${task.status === 'done' ? 'bg-green-500/20 text-green-400' : 'bg-accent-subtle text-accent-primary'}
                                    `}>
                                        {task.status.replace('_', ' ')}
                                    </span>
                                </div>

                                <div>
                                    <label className="text-[10px] font-bold uppercase text-text-tertiary block mb-2">Priority</label>
                                    <div className="flex items-center gap-2">
                                        <div className="w-2 h-2 rounded-full" style={{ backgroundColor: priorityColors[task.priority] }} />
                                        <span className="text-sm text-text-secondary capitalize">{task.priority}</span>
                                    </div>
                                </div>

                                <div>
                                    <label className="text-[10px] font-bold uppercase text-text-tertiary block mb-2">Assignee</label>
                                    <div className="flex items-center gap-2">
                                        <div className="w-6 h-6 rounded-full bg-accent-subtle flex items-center justify-center text-[10px] font-bold text-accent-primary">
                                            {task.assignee ? task.assignee[0].toUpperCase() : '?'}
                                        </div>
                                        <span className="text-sm text-text-secondary">{task.assignee || 'Unassigned'}</span>
                                    </div>
                                </div>

                                <div>
                                    <label className="text-[10px] font-bold uppercase text-text-tertiary block mb-2">Labels</label>
                                    <div className="flex flex-wrap gap-1.5">
                                        {(task.tags || []).length > 0 ? task.tags.map(t => (
                                            <span key={t} className="text-[10px] font-medium bg-bg-app px-2 py-0.5 rounded border border-border-subtle text-text-secondary">
                                                {t}
                                            </span>
                                        )) : <span className="text-xs text-text-tertiary italic">None</span>}
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* Definition of Done */}
                        <div className="bg-bg-card border border-border-subtle rounded-xl p-6 shadow-sm">
                            <div className="flex items-center justify-between mb-4">
                                <h3 className="text-xs font-bold uppercase text-text-primary flex items-center gap-1.5">
                                    <CheckSquare className="w-3.5 h-3.5" /> Definition of Done
                                </h3>
                                {dodItems.length > 0 && (
                                    <span className="text-xs text-text-secondary">
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
                        </div>

                        {/* Git Integration */}
                        <div className="bg-bg-card border border-border-subtle rounded-xl p-6 shadow-sm">
                            <h3 className="text-xs font-bold uppercase text-text-primary flex items-center gap-1.5 mb-4">
                                <GitBranch className="w-3.5 h-3.5" /> Git
                            </h3>

                            {/* Branch */}
                            <div className="mb-4">
                                <div className="text-[10px] font-bold uppercase text-text-secondary mb-1">Branch</div>
                                {editingBranch ? (
                                    <input
                                        className="w-full px-2 py-1.5 text-sm bg-bg-app border border-border-subtle rounded font-mono text-text-primary focus:outline-none focus:border-accent-primary"
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
                                            <span className="text-xs text-text-tertiary italic cursor-pointer hover:text-text-secondary" onClick={() => setEditingBranch(true)}>No branch set</span>
                                        )}
                                    </div>
                                )}
                            </div>

                            {/* PR URL */}
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
                                            <span className="text-xs text-text-tertiary italic cursor-pointer hover:text-text-secondary" onClick={() => setEditingPrUrl(true)}>No PR linked</span>
                                        )}
                                    </div>
                                )}
                            </div>

                            {/* Commits list */}
                            {commits.length > 0 && (
                                <>
                                    <div className="text-[10px] font-bold uppercase text-text-secondary mb-1.5">Commits & PRs ({commits.length})</div>
                                    <div className="space-y-1.5">
                                        {commits.map((c) => (
                                            <div key={c.id} className="flex items-center gap-2 px-2.5 py-1.5 rounded bg-bg-app border border-border-subtle/30 text-sm">
                                                {c.kind === 'pr'
                                                    ? <GitPullRequest className="w-3.5 h-3.5 text-purple-400 flex-shrink-0" />
                                                    : <GitCommit className="w-3.5 h-3.5 text-text-secondary flex-shrink-0" />
                                                }
                                                <div className="flex-1 min-w-0">
                                                    <div className="text-text-primary truncate text-xs">
                                                        {c.kind === 'pr' ? `#${c.pr_number} ` : `${c.sha.slice(0, 7)} `}{c.message}
                                                    </div>
                                                    <div className="text-[10px] text-text-secondary">
                                                        {c.author}{c.branch ? ` on ${c.branch}` : ''}
                                                        {c.kind === 'pr' && c.pr_state && (
                                                            <span className={`ml-1.5 px-1 py-0.5 rounded text-[9px] font-medium ${
                                                                c.pr_state === 'merged' ? 'bg-purple-500/20 text-purple-400' :
                                                                c.pr_state === 'open' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                                                            }`}>{c.pr_state}</span>
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

                        <div className="bg-bg-card border border-border-subtle rounded-xl p-6 shadow-sm">
                            <h3 className="text-xs font-bold uppercase text-text-secondary mb-4">Timestamps</h3>
                            <div className="space-y-3">
                                <div className="flex items-center gap-2 text-text-secondary">
                                    <Calendar className="w-3.5 h-3.5" />
                                    <span className="text-xs">Created: {new Date(task.created_at).toLocaleDateString()}</span>
                                </div>
                                <div className="flex items-center gap-2 text-text-secondary">
                                    <Clock className="w-3.5 h-3.5" />
                                    <span className="text-xs">Updated: {new Date(task.updated_at).toLocaleDateString()}</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
