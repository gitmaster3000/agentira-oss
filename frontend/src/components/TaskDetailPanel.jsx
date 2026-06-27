import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../context/AuthContext';
import { ROUTES } from '../routes';
import { Markdown } from './Markdown';
import { MentionInput } from './MentionInput';
import {
    Trash2, X, ExternalLink, Pencil, CheckSquare, Square, Plus,
    GitCommit, GitPullRequest, GitBranch, Copy, Check, Send,
    Info, FileText, MessageSquare, Activity as ActivityIcon, Paperclip,
    Play, Cpu,
} from 'lucide-react';
import { ConfirmModal } from './ConfirmModal';

// Board status → dot color + label (design: guidelines/colors-semantic.html).
const STATUS = {
    backlog:     { color: '#768390', label: 'Backlog' },
    todo:        { color: '#8ab4f8', label: 'To Do' },
    in_progress: { color: '#ff9800', label: 'In Progress' },
    review:      { color: '#7c4dff', label: 'In Review' },
    done:        { color: '#2ecc71', label: 'Done' },
};
const LIVE_RUN_STATUSES = ['pending', 'running', 'interrupting'];

const RAIL = [
    { id: 'info', label: 'Details', icon: Info },
    { id: 'files', label: 'Files', icon: FileText },
    { id: 'git', label: 'Branch & PR', icon: GitBranch },
    { id: 'comments', label: 'Comments', icon: MessageSquare },
    { id: 'activity', label: 'Activity', icon: ActivityIcon },
];

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
function initials(name) {
    if (!name) return '?';
    return name.slice(0, 2).toUpperCase();
}
function relTime(value) {
    if (!value) return '';
    const diff = Math.round((Date.now() - new Date(value).getTime()) / 1000);
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
    return new Date(value).toLocaleDateString();
}

export function TaskDetailPanel({ task, onClose, onUpdate, isEditing, setIsEditing }) {
    const navigate = useNavigate();
    const { user } = useAuth();
    const [activities, setActivities] = useState([]);
    const [isConfirmingDelete, setIsConfirmingDelete] = useState(false);
    const [comment, setComment] = useState('');
    const [attachments, setAttachments] = useState([]);
    const [commits, setCommits] = useState([]);
    const [dodItems, setDodItems] = useState(task.dod_items || []);
    const [newDodText, setNewDodText] = useState('');
    const [taskRuns, setTaskRuns] = useState([]);
    const [profiles, setProfiles] = useState([]);
    const [epics, setEpics] = useState([]);
    const [forgeAgents, setForgeAgents] = useState([]);
    const [pickingAgent, setPickingAgent] = useState(false);
    const [scheduling, setScheduling] = useState(false);
    const [editingBranch, setEditingBranch] = useState(false);
    const [branchValue, setBranchValue] = useState(task.branch || '');
    const [editingPrUrl, setEditingPrUrl] = useState(false);
    const [prUrlValue, setPrUrlValue] = useState(task.pr_url || '');
    const [copiedField, setCopiedField] = useState(null);
    const [formData, setFormData] = useState({ ...task });
    const [activeSection, setActiveSection] = useState('info');

    const scrollRef = useRef(null);
    const sectionRefs = useRef({});
    const fileInputRef = useRef(null);

    const toggleEditing = (val) => setIsEditing(val);

    useEffect(() => {
        setIsEditing(false);
        setFormData({ ...task });
    }, [task.id]);

    useEffect(() => {
        loadActivity();
        loadAttachments();
        loadCommits();
        loadTaskRuns();
        setDodItems(task.dod_items || []);
        setBranchValue(task.branch || '');
        setPrUrlValue(task.pr_url || '');
        if (task.project_id) api.getProjectMembers(task.project_id).then(setProfiles).catch(() => {});
        if (task.project_id) api.getEpics(task.project_id).then(d => setEpics(Array.isArray(d) ? d : [])).catch(() => {});
        const interval = setInterval(() => { loadActivity(); loadTaskRuns(); }, 3000);
        return () => clearInterval(interval);
    }, [task.id]);

    // Keep the read-only Branch/PR display in sync when the task's values
    // change without the id changing — e.g. after saving in edit mode (the
    // parent refetches the same task) or a webhook update. Without this the
    // [task.id] effect above never re-runs and edits appear not to persist.
    useEffect(() => {
        setBranchValue(task.branch || '');
        setPrUrlValue(task.pr_url || '');
    }, [task.branch, task.pr_url]);

    const loadTaskRuns = async () => {
        try {
            const data = await api.forge.listTaskRuns(task.id);
            if (Array.isArray(data)) setTaskRuns(data);
        } catch { /* forge may be down */ }
    };
    const loadActivity = async () => {
        try { setActivities(await api.getActivity(task.id)); } catch (err) { console.error(err); }
    };
    const loadAttachments = async () => {
        try {
            const data = await api.listAttachments(task.id);
            if (Array.isArray(data)) setAttachments(data);
        } catch { /* ignore */ }
    };
    const loadCommits = async () => {
        try {
            const data = await api.listTaskCommits(task.id);
            if (Array.isArray(data)) setCommits(data);
        } catch { /* ignore */ }
    };
    const saveBranch = async (val) => {
        setEditingBranch(false);
        if (val !== (task.branch || '')) {
            try { await api.updateTask(task.id, { branch: val }); onUpdate(); } catch (err) { console.error(err); }
        }
    };
    const savePrUrl = async (val) => {
        setEditingPrUrl(false);
        if (val !== (task.pr_url || '')) {
            try { await api.updateTask(task.id, { pr_url: val }); onUpdate(); } catch (err) { console.error(err); }
        }
    };
    const copyToClipboard = (text, field) => {
        navigator.clipboard.writeText(text);
        setCopiedField(field);
        setTimeout(() => setCopiedField(null), 800);
    };
    const toggleDodItem = async (index) => {
        const updated = dodItems.map((item, i) => i === index ? { ...item, checked: !item.checked } : item);
        setDodItems(updated);
        try { await api.updateTask(task.id, { dod_items: updated }); onUpdate(); } catch (err) { console.error(err); }
    };
    const addDodItem = async () => {
        if (!newDodText.trim()) return;
        const updated = [...dodItems, { text: newDodText.trim(), checked: false }];
        setDodItems(updated);
        setNewDodText('');
        try { await api.updateTask(task.id, { dod_items: updated }); onUpdate(); } catch (err) { console.error(err); }
    };
    const removeDodItem = async (index) => {
        const updated = dodItems.filter((_, i) => i !== index);
        setDodItems(updated);
        try { await api.updateTask(task.id, { dod_items: updated }); onUpdate(); } catch (err) { console.error(err); }
    };
    const handleUpload = async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        try { await api.uploadAttachment(task.id, file); loadAttachments(); loadActivity(); }
        catch (err) { alert(err.message); }
        finally { e.target.value = ''; }
    };
    const handleDeleteAttachment = async (id, filename) => {
        if (!confirm(`Delete attachment "${filename}"?`)) return;
        try { await api.deleteAttachment(id); loadAttachments(); loadActivity(); }
        catch (err) { alert(err.message); }
    };
    const handleSave = async () => {
        try {
            // Edit mode edits everything, including Branch & PR.
            await api.updateTask(task.id, {
                title: formData.title,
                description: formData.description,
                branch: formData.branch || '',
                pr_url: formData.pr_url || '',
            });
            toggleEditing(false);
            onUpdate();
        } catch (err) { alert(err.message); }
    };

    // Status/priority/assignee are inline-editable (no edit mode) — save on change.
    const saveField = async (patch) => {
        try { await api.updateTask(task.id, patch); onUpdate(); }
        catch (err) { alert(err.message); }
    };
    const saveStatus = async (s) => {
        if (s === task.status) return;
        // Dedicated /move endpoint drives transitions/activity.
        try { await api.moveTask(task.id, s); onUpdate(); }
        catch (err) { alert(err.message); }
    };

    const openAgentPicker = async () => {
        setPickingAgent(true);
        try {
            const data = await api.forge.listAgents();
            setForgeAgents((Array.isArray(data) ? data : []).filter(a => a.runtime_id));
        } catch (err) {
            console.error('Failed to load agents:', err);
            setForgeAgents([]);
        }
    };

    const handleScheduleRun = async (agentId) => {
        setScheduling(true);
        try {
            const result = await api.forge.prepareTaskRun(task.id, agentId);
            setPickingAgent(false);
            await loadTaskRuns();
            const runId = result.id || result.run_id;
            if (runId) navigate(ROUTES.FORGE_RUN(runId));
        } catch (err) {
            console.error('Prepare run failed:', err);
            alert('Failed to prepare run: ' + (err.message || err));
        } finally {
            setScheduling(false);
        }
    };
    const handleComment = async (e) => {
        if (e) e.preventDefault();
        if (!comment.trim()) return;
        try { await api.addComment(task.id, { comment }); setComment(''); loadActivity(); }
        catch (err) { alert(err.message); }
    };
    const handleDelete = async () => {
        try { await api.deleteTask(task.id); onUpdate(); }
        catch (err) { alert(err.message); setIsConfirmingDelete(false); }
    };

    // Measure section offsets via getBoundingClientRect so the math is
    // independent of offsetParent (the scroll container isn't positioned).
    const scrollTo = (id) => {
        const el = sectionRefs.current[id];
        const c = scrollRef.current;
        if (el && c) {
            const top = el.getBoundingClientRect().top - c.getBoundingClientRect().top + c.scrollTop - 12;
            c.scrollTo({ top, behavior: 'smooth' });
        }
        setActiveSection(id);
    };
    const onScroll = () => {
        const c = scrollRef.current;
        if (!c) return;
        const cTop = c.getBoundingClientRect().top;
        let current = 'info';
        for (const { id } of RAIL) {
            const el = sectionRefs.current[id];
            if (el && el.getBoundingClientRect().top - cTop <= 28) current = id;
        }
        setActiveSection(current);
    };

    const status = STATUS[task.status] || { color: '#768390', label: task.status };
    const liveRun = taskRuns.find(r => LIVE_RUN_STATUSES.includes(r.status));
    const workRuns = taskRuns.filter(r => r.is_work);
    const comments = activities.filter(a => a.action === 'commented');
    const doneCount = dodItems.filter(i => i.checked).length;

    // Branch & PR are a per-repo 1:1 mapping. Surface which repo they belong to
    // so multi-repo tasks read correctly. `repo_name`/`repos` come from the API
    // (repos[0] is the task's first declared repo; falls back to primary repo).
    const taskRepos = task.repos || [];
    const gitRepoLabel = task.repo_name || taskRepos[0] || '';
    const isMultiRepo = taskRepos.length > 1;

    return (
        <aside
            className="h-full flex flex-col flex-shrink-0 animate-slide-in"
            style={{ width: 384, background: 'var(--bg-panel)', borderLeft: '1px solid var(--border-subtle)' }}
            onClick={e => e.stopPropagation()}
        >
            {/* Header: key + epic · open full / edit / delete / close.
                Fixed 53px height matches the board toolbar so the panel's top
                divider lines up with the board header's bottom border. While
                editing, the edit/delete pair swaps to Save/Cancel — the same
                standard used on the Epic page. */}
            <div className="flex items-center gap-2 flex-shrink-0" style={{ padding: '0 18px', height: 53, borderBottom: '1px solid var(--border-subtle)' }}>
                <span style={{ fontSize: 12, fontFamily: 'ui-monospace,monospace', fontWeight: 600, color: '#7c8db5', whiteSpace: 'nowrap' }}>
                    {task.key || task.id}
                </span>
                <div className="flex-1" />
                {isEditing ? (
                    <>
                        <button onClick={handleSave} title="Save changes" className="flex items-center gap-1.5 transition-colors" style={{ padding: '6px 12px', borderRadius: 8, fontSize: 11.5, fontWeight: 600, background: 'var(--accent-primary)', color: '#fff' }}>
                            <Check className="w-3.5 h-3.5" /> Save
                        </button>
                        <button onClick={() => { toggleEditing(false); setFormData({ ...task }); }} title="Cancel" className="flex items-center gap-1.5 text-text-secondary hover:text-text-primary transition-colors" style={{ padding: '6px 11px', borderRadius: 8, border: '1px solid var(--border-subtle)', fontSize: 11.5, fontWeight: 500 }}>
                            <X className="w-3.5 h-3.5" /> Cancel
                        </button>
                    </>
                ) : (
                    <>
                        <button
                            onClick={() => navigate(ROUTES.STUDIO_TASK(task.key || task.id))}
                            className="flex items-center gap-1.5 text-text-tertiary hover:text-text-primary transition-colors"
                            style={{ padding: '6px 11px', borderRadius: 8, border: '1px solid var(--border-subtle)', fontSize: 11.5 }}
                            title="Open full task page"
                        >
                            <ExternalLink className="w-3 h-3" /> Open full
                        </button>
                        <button onClick={() => { setFormData({ ...task }); toggleEditing(true); }} title="Edit" className="flex items-center justify-center text-text-tertiary hover:text-text-primary hover:bg-bg-card transition-colors" style={{ width: 28, height: 28, borderRadius: 8 }}>
                            <Pencil className="w-4 h-4" />
                        </button>
                        <button onClick={() => setIsConfirmingDelete(true)} title="Delete" className="flex items-center justify-center text-text-tertiary hover:text-red-400 transition-colors" style={{ width: 28, height: 28, borderRadius: 8 }}>
                            <Trash2 className="w-4 h-4" />
                        </button>
                    </>
                )}
                {/* In edit mode the Cancel button covers dismissal, so the
                    standalone close (X) is hidden to avoid a redundant cross. */}
                {!isEditing && (
                    <button onClick={onClose} title="Close" className="flex items-center justify-center text-text-tertiary hover:text-text-primary hover:bg-bg-card transition-colors" style={{ width: 28, height: 28, borderRadius: 8 }}>
                        <X className="w-4 h-4" />
                    </button>
                )}
            </div>

            {/* Title */}
            <div style={{ padding: '15px 18px 13px' }}>
                {isEditing ? (
                    <input
                        className="w-full bg-bg-app border border-border-subtle rounded-lg p-2 text-text-primary focus:outline-none focus:border-accent-primary"
                        style={{ fontSize: 17.5, fontWeight: 600 }}
                        value={formData.title}
                        onChange={e => setFormData({ ...formData, title: e.target.value })}
                        maxLength={255}
                        autoFocus
                    />
                ) : (
                    // Clamp to 3 lines so a long title can't push the divider below
                    // out of alignment; full title stays available on hover.
                    <h2
                        title={task.title}
                        style={{ fontSize: 17.5, fontWeight: 600, margin: 0, lineHeight: 1.3, display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}
                        className="text-text-primary"
                    >
                        {task.title}
                    </h2>
                )}
            </div>

            <div className="flex-1 flex min-h-0" style={{ borderTop: '1px solid var(--border-subtle)' }}>
                {/* Icon rail */}
                <nav className="flex flex-col items-center flex-shrink-0" style={{ width: 50, borderRight: '1px solid var(--border-subtle)', gap: 4, padding: '10px 0' }}>
                    {RAIL.map(({ id, label, icon: Icon }) => {
                        const active = activeSection === id;
                        return (
                            <button
                                key={id}
                                onClick={() => scrollTo(id)}
                                title={label}
                                className="flex items-center justify-center transition-colors"
                                style={{
                                    width: 34, height: 34, borderRadius: 8,
                                    color: active ? '#c9b8ff' : '#768390',
                                    background: active ? 'rgba(201,184,255,.12)' : 'transparent',
                                }}
                            >
                                <Icon className="w-4 h-4" />
                            </button>
                        );
                    })}
                </nav>

                {/* Scroll body */}
                <div ref={scrollRef} onScroll={onScroll} className="flex-1 min-w-0 overflow-y-auto custom-scrollbar" style={{ padding: '16px 18px', position: 'relative', scrollBehavior: 'smooth' }}>
                    {/* INFO */}
                    <div ref={el => (sectionRefs.current.info = el)}>
                        {liveRun && (
                            <div
                                onClick={() => navigate(ROUTES.FORGE_RUN(liveRun.id))}
                                className="agent-active-glow flex items-center gap-2 cursor-pointer"
                                style={{ padding: 10, borderRadius: 10, background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', marginBottom: 16 }}
                            >
                                <span style={{ width: 24, height: 24, borderRadius: 7, background: 'rgba(0,188,212,.14)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#00bcd4" strokeWidth="2"><rect x="3" y="11" width="18" height="10" rx="2"></rect><circle cx="12" cy="5" r="2"></circle><path d="M12 7v4"></path></svg>
                                </span>
                                <div className="flex-1 min-w-0">
                                    <div style={{ fontSize: 12, fontWeight: 600 }} className="text-text-primary">Agent working now</div>
                                    <div style={{ fontSize: 10.5 }} className="text-text-tertiary">Open to watch the live run</div>
                                </div>
                                <span className="flex items-center" style={{ gap: 5, fontSize: 10, fontWeight: 700, color: '#38bdf8' }}>
                                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#38bdf8' }} />LIVE
                                </span>
                            </div>
                        )}

                        {/* AP-301: launch a run from the side panel. */}
                        <div className="flex items-center justify-between" style={{ marginBottom: 10 }}>
                            <SectionLabel inline>Agent runs</SectionLabel>
                            <button
                                onClick={pickingAgent ? () => setPickingAgent(false) : openAgentPicker}
                                className="inline-flex items-center transition-colors"
                                style={{ gap: 5, fontSize: 11, fontWeight: 600, padding: '4px 9px', borderRadius: 7, background: 'var(--accent-subtle, rgba(124,77,255,.14))', color: 'var(--accent-primary, #7c4dff)' }}
                            >
                                <Play className="w-3 h-3" /> {pickingAgent ? 'Cancel' : 'Run with agent'}
                            </button>
                        </div>
                        {pickingAgent && (
                            <div style={{ marginBottom: 16, padding: 10, borderRadius: 10, border: '1px solid var(--border-subtle)', background: 'var(--bg-app)' }}>
                                {forgeAgents.length === 0 ? (
                                    <p style={{ fontSize: 11.5 }} className="text-text-tertiary">No online agents bound to a runtime. Create one in Forge first.</p>
                                ) : (
                                    [...forgeAgents].sort((a, b) => {
                                        const aA = task?.assignee && a.name === task.assignee;
                                        const bA = task?.assignee && b.name === task.assignee;
                                        if (aA && !bA) return -1;
                                        if (bA && !aA) return 1;
                                        return (a.name || '').localeCompare(b.name || '');
                                    }).map(a => {
                                        const online = a.status === 'online';
                                        const isAssigned = task?.assignee && a.name === task.assignee;
                                        return (
                                            <button
                                                key={a.id}
                                                disabled={scheduling || !online}
                                                onClick={() => handleScheduleRun(a.id)}
                                                className="w-full flex items-center transition-colors"
                                                style={{ gap: 9, padding: '7px 8px', borderRadius: 8, textAlign: 'left', opacity: online ? 1 : 0.5, cursor: online ? 'pointer' : 'not-allowed', border: isAssigned ? '1px solid rgba(124,77,255,.4)' : '1px solid transparent' }}
                                            >
                                                <span style={{ width: 26, height: 26, borderRadius: 7, flexShrink: 0, background: 'var(--bg-card)', fontSize: 11, fontWeight: 700 }} className="flex items-center justify-center text-text-secondary">
                                                    {a.name?.[0]?.toUpperCase() || 'A'}
                                                </span>
                                                <span className="flex-1 min-w-0">
                                                    <span className="flex items-center" style={{ gap: 6 }}>
                                                        <span style={{ fontSize: 12.5 }} className="text-text-primary truncate">{a.name}</span>
                                                        {isAssigned && <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 4, background: 'rgba(124,77,255,.15)', color: '#7c4dff' }}>assignee</span>}
                                                    </span>
                                                    <span style={{ fontSize: 10.5 }} className="text-text-tertiary truncate block">{a.model || a.runtime_type || 'no model'}</span>
                                                </span>
                                                <span style={{ fontSize: 10.5 }} className={online ? 'text-green-400' : 'text-text-tertiary'}>{online ? 'online' : 'offline'}</span>
                                            </button>
                                        );
                                    })
                                )}
                            </div>
                        )}
                        {!pickingAgent && (
                            workRuns.length > 0 ? (
                                <div style={{ marginBottom: 16 }}>
                                    {workRuns.slice(0, 5).map(r => (
                                        <button
                                            key={r.id}
                                            onClick={() => navigate(ROUTES.FORGE_RUN(r.id))}
                                            className="w-full flex items-center transition-colors hover:bg-bg-card"
                                            style={{ gap: 8, padding: '6px 8px', borderRadius: 8, textAlign: 'left' }}
                                        >
                                            <Cpu className="w-3 h-3 flex-shrink-0 text-text-tertiary" />
                                            <span style={{ fontSize: 12 }} className="text-text-primary truncate">{r.agent_name || r.agent_id}</span>
                                            <span style={{ fontSize: 10.5 }} className="text-text-tertiary ml-auto">{r.status}</span>
                                            <span style={{ fontSize: 10 }} className="text-text-tertiary">{relTime(r.created_at)}</span>
                                        </button>
                                    ))}
                                </div>
                            ) : (
                                <p style={{ fontSize: 11.5, marginBottom: 16 }} className="text-text-tertiary">No agent runs yet. Launch one to get started.</p>
                            )
                        )}

                        <SectionLabel>Description</SectionLabel>
                        {isEditing ? (
                            <textarea
                                className="w-full bg-bg-app border border-border-subtle rounded-lg p-2.5 text-text-secondary focus:outline-none focus:border-accent-primary"
                                style={{ fontSize: 12.5, lineHeight: 1.6, minHeight: 90, marginBottom: 18 }}
                                value={formData.description || ''}
                                onChange={e => setFormData({ ...formData, description: e.target.value })}
                            />
                        ) : (
                            <div style={{ fontSize: 12.5, lineHeight: 1.6, marginBottom: 18 }} className="text-text-tertiary break-words">
                                {task.description ? <Markdown>{task.description}</Markdown> : <span className="italic">No description.</span>}
                            </div>
                        )}

                        <div style={{ display: 'grid', gridTemplateColumns: '84px 1fr', gap: '12px 10px', fontSize: 12.5, alignItems: 'center', marginBottom: 18 }}>
                            <span className="text-text-tertiary">Status</span>
                            <span className="inline-flex items-center" style={{ gap: 7 }}>
                                <span style={{ width: 8, height: 8, borderRadius: '50%', background: status.color, flexShrink: 0 }} />
                                <select
                                    className="ghost-select"
                                    value={task.status}
                                    onChange={e => saveStatus(e.target.value)}
                                >
                                    {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
                                </select>
                            </span>
                            <span className="text-text-tertiary">Priority</span>
                            <span>
                                <select
                                    className="ghost-select capitalize"
                                    value={task.priority}
                                    onChange={e => saveField({ priority: e.target.value })}
                                >
                                    {['low', 'medium', 'high', 'critical'].map(p => <option key={p} value={p}>{p}</option>)}
                                </select>
                            </span>
                            <span className="text-text-tertiary">Assignee</span>
                            <span className="inline-flex items-center" style={{ gap: 7 }}>
                                <span style={{ width: 20, height: 20, borderRadius: '50%', background: 'rgba(0,188,212,.16)', color: '#00bcd4', fontSize: 9, fontWeight: 700, flexShrink: 0 }} className="flex items-center justify-center">
                                    {initials(task.assignee)}
                                </span>
                                <select
                                    className="ghost-select"
                                    value={task.assignee || ''}
                                    onChange={e => saveField({ assignee: e.target.value })}
                                >
                                    <option value="">Unassigned</option>
                                    {profiles.map(p => <option key={p.id} value={p.name}>{p.display_name}</option>)}
                                </select>
                            </span>
                            <span className="text-text-tertiary">Epic</span>
                            <span className="inline-flex items-center" style={{ gap: 7 }}>
                                <span style={{ width: 8, height: 8, borderRadius: '50%', background: task.epic_id ? (task.epic_color || '#c9b8ff') : 'transparent', flexShrink: 0 }} />
                                <select
                                    aria-label="Epic"
                                    className="ghost-select"
                                    value={task.epic_id || ''}
                                    onChange={e => saveField({ epic_id: e.target.value })}
                                >
                                    <option value="">No epic</option>
                                    {epics.map(ep => <option key={ep.id} value={ep.id}>{ep.title}</option>)}
                                </select>
                            </span>
                        </div>

                        <div className="flex items-center justify-between" style={{ marginBottom: 9 }}>
                            <SectionLabel inline>Definition of Done</SectionLabel>
                            {dodItems.length > 0 && <span style={{ fontSize: 11 }} className="text-text-tertiary">{doneCount} / {dodItems.length}</span>}
                        </div>
                        {dodItems.map((item, i) => (
                            <div key={i} className="flex items-center group" style={{ gap: 9, fontSize: 12.5, marginBottom: 6 }}>
                                <button onClick={() => toggleDodItem(i)} className="flex-shrink-0 flex items-center justify-center" style={{ width: 16, height: 16, borderRadius: 5, background: item.checked ? '#2ecc71' : 'transparent', border: item.checked ? 'none' : '1.5px solid var(--border-strong, #484f58)' }}>
                                    {item.checked && <Check className="w-2.5 h-2.5" style={{ color: '#0e1117' }} strokeWidth={3} />}
                                </button>
                                <span className="flex-1" style={item.checked ? { color: '#768390', textDecoration: 'line-through' } : { color: '#e8ebf0' }}>{item.text}</span>
                                <button onClick={() => removeDodItem(i)} className="opacity-0 group-hover:opacity-100 text-text-tertiary hover:text-red-400 transition-all"><X className="w-3 h-3" /></button>
                            </div>
                        ))}
                        <div className="flex items-center" style={{ gap: 6, marginTop: 4, marginBottom: 18 }}>
                            <input
                                className="flex-1 bg-bg-app border border-border-subtle rounded text-text-primary focus:outline-none focus:border-accent-primary"
                                style={{ fontSize: 12, padding: '5px 8px' }}
                                placeholder="Add item…"
                                value={newDodText}
                                onChange={e => setNewDodText(e.target.value)}
                                onKeyDown={e => e.key === 'Enter' && addDodItem()}
                            />
                            <button onClick={addDodItem} className="text-text-tertiary hover:text-accent-primary"><Plus className="w-4 h-4" /></button>
                        </div>

                    </div>

                    {/* FILES */}
                    <div ref={el => (sectionRefs.current.files = el)} style={{ borderTop: '1px solid #21262d', marginTop: 20, paddingTop: 18 }}>
                        <SectionLabel>Files</SectionLabel>
                        <div className="flex flex-col" style={{ gap: 8 }}>
                            {attachments.map(att => (
                                <div key={att.id} className="flex items-center group hover:border-border-strong transition-colors" style={{ gap: 10, padding: '10px 12px', borderRadius: 9, background: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}>
                                    <button type="button"
                                       onClick={() => api.downloadAttachment(att.id, att.filename || att.name).catch(err => alert('Failed to download: ' + err.message))}
                                       className="flex items-center min-w-0 flex-1" style={{ gap: 10, textAlign: 'left', cursor: 'pointer' }}>
                                        <FileText className="w-4 h-4 flex-shrink-0" style={{ color: '#80cbc4' }} />
                                        <div className="flex-1 min-w-0">
                                            <div style={{ fontSize: 12.5 }} className="text-text-primary truncate">{att.filename || att.name}</div>
                                            {att.size != null && <div style={{ fontSize: 10.5 }} className="text-text-tertiary">{Math.round(att.size / 1024)} KB</div>}
                                        </div>
                                    </button>
                                    <button type="button"
                                       onClick={() => handleDeleteAttachment(att.id, att.filename || att.name)}
                                       title="Delete attachment"
                                       className="flex-shrink-0 opacity-0 group-hover:opacity-100 text-text-tertiary hover:text-red-400 transition-all">
                                        <Trash2 className="w-3.5 h-3.5" />
                                    </button>
                                </div>
                            ))}
                            <button onClick={() => fileInputRef.current?.click()} className="flex items-center justify-center text-text-tertiary hover:text-text-secondary transition-colors" style={{ gap: 6, marginTop: 4, padding: 10, borderRadius: 9, border: '1px dashed var(--border-subtle)', fontSize: 11.5 }}>
                                <Plus className="w-3 h-3" /> Attach a file
                            </button>
                            <input ref={fileInputRef} type="file" className="hidden" onChange={handleUpload} />
                        </div>
                    </div>

                    {/* GIT */}
                    <div ref={el => (sectionRefs.current.git = el)} style={{ borderTop: '1px solid #21262d', marginTop: 20, paddingTop: 18 }}>
                        {/* Branch & PR are a per-repo 1:1 mapping — show which repo
                            they belong to so multi-repo tasks read unambiguously. */}
                        {gitRepoLabel && (
                            <div className="flex items-center" style={{ gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
                                <span className="inline-flex items-center" style={{ gap: 5, fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 5, textTransform: 'uppercase', letterSpacing: '.04em', background: 'rgba(128,203,196,.12)', color: '#80cbc4' }}>
                                    <GitBranch className="w-3 h-3" /> {gitRepoLabel}
                                </span>
                                {isMultiRepo && <span style={{ fontSize: 10.5 }} className="text-text-tertiary">Branch &amp; PR apply to this repo</span>}
                            </div>
                        )}

                        <SectionLabel>Branch</SectionLabel>
                        <div style={{ marginBottom: 16 }}>
                            {isEditing ? (
                                <input
                                    aria-label="Branch"
                                    className="w-full bg-bg-app border border-border-subtle rounded-lg font-mono text-text-primary focus:outline-none focus:border-accent-primary"
                                    style={{ fontSize: 12, padding: '9px 11px' }}
                                    value={formData.branch || ''}
                                    onChange={e => setFormData({ ...formData, branch: e.target.value })}
                                    placeholder="feature/my-branch"
                                />
                            ) : editingBranch ? (
                                <input
                                    className="w-full bg-bg-card border border-border-subtle rounded-lg font-mono text-text-primary focus:outline-none focus:border-accent-primary"
                                    style={{ fontSize: 12, padding: '9px 11px' }}
                                    value={branchValue}
                                    onChange={e => setBranchValue(e.target.value)}
                                    onBlur={() => saveBranch(branchValue)}
                                    onKeyDown={e => e.key === 'Enter' && saveBranch(branchValue)}
                                    autoFocus
                                />
                            ) : branchValue ? (
                                <div className="flex items-center" style={{ gap: 8, padding: '9px 11px', borderRadius: 9, background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', fontSize: 12 }}>
                                    <GitBranch className="w-3.5 h-3.5 flex-shrink-0" style={{ color: '#80cbc4' }} />
                                    <span className="flex-1 font-mono truncate" style={{ color: '#b1bac4' }}>{formatBranchDisplay(branchValue)}</span>
                                    <button onClick={() => setEditingBranch(true)} className="text-text-tertiary hover:text-text-secondary"><Pencil className="w-3 h-3" /></button>
                                    <button onClick={() => copyToClipboard(branchValue, 'branch')} className="text-text-tertiary hover:text-accent-primary">{copiedField === 'branch' ? <Check className="w-3 h-3 text-green-500" /> : <Copy className="w-3 h-3" />}</button>
                                </div>
                            ) : (
                                <button onClick={() => setEditingBranch(true)} className="text-text-tertiary italic hover:text-text-secondary" style={{ fontSize: 12 }}>No branch set</button>
                            )}
                        </div>

                        <SectionLabel>Pull Request</SectionLabel>
                        <div style={{ marginBottom: 16 }}>
                            {isEditing ? (
                                <input
                                    aria-label="Pull Request"
                                    className="w-full bg-bg-app border border-border-subtle rounded-lg text-text-primary focus:outline-none focus:border-accent-primary"
                                    style={{ fontSize: 12, padding: '9px 11px' }}
                                    value={formData.pr_url || ''}
                                    onChange={e => setFormData({ ...formData, pr_url: e.target.value })}
                                    placeholder="https://github.com/…"
                                />
                            ) : editingPrUrl ? (
                                <input
                                    className="w-full bg-bg-card border border-border-subtle rounded-lg text-text-primary focus:outline-none focus:border-accent-primary"
                                    style={{ fontSize: 12, padding: '9px 11px' }}
                                    value={prUrlValue}
                                    onChange={e => setPrUrlValue(e.target.value)}
                                    onBlur={() => savePrUrl(prUrlValue)}
                                    onKeyDown={e => e.key === 'Enter' && savePrUrl(prUrlValue)}
                                    placeholder="https://github.com/…"
                                    autoFocus
                                />
                            ) : prUrlValue ? (
                                <a href={prUrlValue} target="_blank" rel="noopener noreferrer" className="flex items-center hover:border-border-strong transition-colors" style={{ gap: 8, padding: '9px 11px', borderRadius: 9, background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', fontSize: 12.5 }}>
                                    <GitPullRequest className="w-3.5 h-3.5 flex-shrink-0" style={{ color: '#a78bfa' }} />
                                    <span className="flex-1 font-mono truncate" style={{ color: '#80cbc4' }}>{formatPrDisplay(prUrlValue)}</span>
                                    <ExternalLink className="w-3 h-3 text-text-tertiary" />
                                </a>
                            ) : (
                                <button onClick={() => setEditingPrUrl(true)} className="text-text-tertiary italic hover:text-text-secondary" style={{ fontSize: 12 }}>No PR linked</button>
                            )}
                        </div>

                        {commits.length > 0 && (
                            <div className="flex flex-col" style={{ gap: 6 }}>
                                {commits.map(c => (
                                    <div key={c.id} className="flex items-center" style={{ gap: 8, padding: '7px 9px', borderRadius: 8, background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', fontSize: 11.5 }}>
                                        {c.kind === 'pr' ? <GitPullRequest className="w-3.5 h-3.5 flex-shrink-0" style={{ color: '#a78bfa' }} /> : <GitCommit className="w-3.5 h-3.5 flex-shrink-0 text-text-tertiary" />}
                                        <span className="flex-1 truncate text-text-secondary">{c.kind === 'pr' ? `#${c.pr_number} ` : `${c.sha?.slice(0, 7)} `}{c.message}</span>
                                        {c.url && <a href={c.url} target="_blank" rel="noopener noreferrer" className="text-text-tertiary hover:text-accent-primary"><ExternalLink className="w-3 h-3" /></a>}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* COMMENTS */}
                    <div ref={el => (sectionRefs.current.comments = el)} style={{ borderTop: '1px solid #21262d', marginTop: 20, paddingTop: 18 }}>
                        <SectionLabel>Comments</SectionLabel>
                        {/* Composer sits ABOVE the thread so it's the first thing
                            you reach, and grows with what you type. */}
                        <form onSubmit={handleComment} className="flex items-end" style={{ gap: 8, marginBottom: 16 }}>
                            <span style={{ width: 26, height: 26, borderRadius: '50%', flexShrink: 0, background: 'var(--bg-card)', color: '#b1bac4', fontSize: 9.5, fontWeight: 700 }} className="flex items-center justify-center">{user?.display_name?.[0]?.toUpperCase() || 'U'}</span>
                            <div className="flex-1 min-w-0" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 10, padding: '6px 10px' }}>
                                <MentionInput
                                    multiline
                                    autoGrow
                                    rows={2}
                                    className="block w-full bg-transparent text-text-primary text-xs leading-relaxed focus:outline-none resize-none max-h-32 overflow-y-auto"
                                    placeholder="Comment or @mention…  (Shift+Enter for a new line)"
                                    value={comment}
                                    onChange={setComment}
                                    onSubmit={handleComment}
                                    projectId={task.project_id}
                                />
                            </div>
                            <button
                                type="submit"
                                disabled={!comment.trim()}
                                title="Send comment"
                                className="flex items-center justify-center flex-shrink-0 transition-colors"
                                style={{
                                    width: 32, height: 32, borderRadius: '50%',
                                    background: comment.trim() ? 'var(--accent-primary)' : 'var(--bg-card)',
                                    color: comment.trim() ? '#2d1a6e' : 'var(--text-tertiary)',
                                    border: '1px solid var(--border-subtle)',
                                    cursor: comment.trim() ? 'pointer' : 'not-allowed',
                                }}
                            >
                                <Send className="w-3.5 h-3.5" />
                            </button>
                        </form>
                        <div className="flex flex-col" style={{ gap: 13 }}>
                            {comments.length === 0 && <p style={{ fontSize: 12 }} className="text-text-tertiary italic">No comments yet.</p>}
                            {comments.map(c => (
                                <div key={c.id} className="flex" style={{ gap: 9 }}>
                                    <span style={{ width: 26, height: 26, borderRadius: '50%', flexShrink: 0, background: 'rgba(201,184,255,.16)', color: '#c9b8ff', fontSize: 9.5, fontWeight: 700 }} className="flex items-center justify-center">{initials(c.actor)}</span>
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center" style={{ gap: 7, marginBottom: 3 }}>
                                            <span style={{ fontSize: 12, fontWeight: 600 }} className="text-text-primary">{c.actor}</span>
                                            <span style={{ fontSize: 10 }} className="text-text-tertiary">{relTime(c.created_at)}</span>
                                        </div>
                                        <div className="text-text-secondary" style={{ fontSize: 12.5, lineHeight: 1.55, background: 'var(--bg-card)', borderRadius: 10, borderTopLeftRadius: 3, padding: '9px 11px' }}>{c.detail}</div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* ACTIVITY */}
                    <div ref={el => (sectionRefs.current.activity = el)} style={{ borderTop: '1px solid #21262d', marginTop: 20, paddingTop: 18 }}>
                        <SectionLabel>Activity</SectionLabel>
                        <div className="flex flex-col">
                            {activities.map((a, i) => (
                                <div key={a.id} className="flex" style={{ gap: 11 }}>
                                    <div className="flex flex-col items-center">
                                        <span style={{ width: 9, height: 9, borderRadius: '50%', background: '#00bcd4', marginTop: 3 }} />
                                        {i < activities.length - 1 && <span className="flex-1" style={{ width: 1.5, background: 'var(--border-subtle)' }} />}
                                    </div>
                                    <div style={{ paddingBottom: 16 }}>
                                        <div style={{ fontSize: 12.5, lineHeight: 1.45 }} className="text-text-primary">
                                            <b>{a.actor}</b> <span className="text-accent-primary">{a.action}</span> {a.detail}
                                        </div>
                                        <div style={{ fontSize: 10.5, marginTop: 2 }} className="text-text-tertiary">{relTime(a.created_at)} ago</div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                    <div style={{ height: 80 }} />
                </div>
            </div>

            {isConfirmingDelete && (
                <ConfirmModal
                    title="Delete Task"
                    message={`Are you sure you want to delete task "${task.title}"?`}
                    confirmText="Delete"
                    onConfirm={handleDelete}
                    onCancel={() => setIsConfirmingDelete(false)}
                />
            )}
        </aside>
    );
}

function SectionLabel({ children, inline }) {
    return (
        <div style={{ fontSize: 12.5, fontWeight: 800, letterSpacing: '.06em', color: '#e8ebf0', marginBottom: inline ? 0 : 11, textTransform: 'uppercase' }}>
            {children}
        </div>
    );
}
