import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Pencil, Trash2, ListTodo, Check, X, Sparkles, Paperclip, Upload } from 'lucide-react';
import { api } from '../api';
import { ROUTES } from '../routes';
import { Breadcrumbs } from '../components/Breadcrumbs';
import { Markdown } from '../components/Markdown';
import { setCurrentProjectId } from '../currentProject';

const PRIORITY_DOTS = {
    critical: '#e74c3c',
    high:     '#ff9800',
    medium:   '#f1c40f',
    low:      '#5f6368',
};

const STATUS_COLORS = {
    backlog:     '#5f6368',
    todo:        '#00bcd4',
    in_progress: '#7c4dff',
    review:      '#ff9800',
    done:        '#2ecc71',
};

const EPIC_COLORS = [
    '#7c4dff', '#00bcd4', '#2ecc71', '#f1c40f',
    '#e67e22', '#e74c3c', '#3498db', '#9b59b6',
];

export function EpicPage() {
    const { epicId } = useParams();
    const navigate = useNavigate();
    const [epic, setEpic] = useState(null);
    const [tasks, setTasks] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [editing, setEditing] = useState(false);
    const [saving, setSaving] = useState(false);
    const [form, setForm] = useState({ title: '', description: '', color: '#7c4dff' });
    const [showPlan, setShowPlan] = useState(false);
    const [attachments, setAttachments] = useState([]);

    const loadAttachments = React.useCallback(async () => {
        try { setAttachments(await api.listEpicAttachments(epicId)); } catch { /* ignore */ }
    }, [epicId]);
    useEffect(() => { loadAttachments(); }, [loadAttachments]);

    useEffect(() => {
        let cancelled = false;
        async function load() {
            setLoading(true);
            try {
                const [e, ts] = await Promise.all([
                    api.getEpic(epicId),
                    api.getEpicTasks(epicId),
                ]);
                if (!cancelled) {
                    setEpic(e);
                    setTasks(Array.isArray(ts) ? ts : []);
                    if (e?.project_id) setCurrentProjectId(e.project_id);
                }
            } catch (err) {
                if (!cancelled) setError(err.message || 'Failed to load epic');
            } finally {
                if (!cancelled) setLoading(false);
            }
        }
        load();
        return () => { cancelled = true; };
    }, [epicId]);

    const startEdit = () => {
        setForm({
            title: epic.title || '',
            description: epic.description || '',
            color: epic.color || '#7c4dff',
        });
        setEditing(true);
    };

    const handleSave = async () => {
        if (!form.title.trim()) return;
        setSaving(true);
        try {
            const updated = await api.updateEpic(epicId, {
                title: form.title.trim(),
                description: form.description,
                color: form.color,
            });
            setEpic(updated);
            setEditing(false);
        } catch (err) {
            alert('Update failed: ' + (err.message || err));
        } finally {
            setSaving(false);
        }
    };

    const handleDelete = async () => {
        if (!window.confirm(`Delete epic "${epic.title}"? Tasks are detached, not deleted.`)) return;
        try {
            await api.deleteEpic(epicId);
            navigate(epic.project_id ? ROUTES.STUDIO_BOARD(epic.project_id) : ROUTES.STUDIO);
        } catch (err) { alert('Delete failed: ' + (err.message || err)); }
    };

    if (loading) {
        return <div className="flex-1 flex items-center justify-center text-text-tertiary p-6">Loading epic…</div>;
    }
    if (error || !epic) {
        return <div className="flex-1 flex items-center justify-center text-red-400 p-6">{error || 'Epic not found.'}</div>;
    }

    const total = tasks.length;
    const done = tasks.filter(t => t.status === 'done').length;
    const inProgress = tasks.filter(t => t.status === 'in_progress' || t.status === 'review').length;

    return (
        // AP-183: the page fills available height and does NOT scroll as a whole;
        // header, description and stats stay pinned and only the Tasks list scrolls.
        <div className="flex-1 flex flex-col overflow-hidden">
            <div className="max-w-5xl w-full mx-auto p-6 flex flex-col gap-6 flex-1 min-h-0">
            <Breadcrumbs entity="epic" data={epic} />

            {/* AP-183: editing happens inline on the page (not a popup). The Edit
                button swaps the title + description into editable fields with a
                color picker, plus Save / Cancel actions. */}
            <div className="flex items-center gap-3">
                <span
                    className="w-3 h-3 rounded-full flex-shrink-0"
                    style={{ backgroundColor: (editing ? form.color : epic.color) || '#7c4dff' }}
                />
                {editing ? (
                    <input
                        autoFocus
                        className="input flex-1 min-w-0 text-2xl font-bold"
                        value={form.title}
                        onChange={e => setForm({ ...form, title: e.target.value })}
                        maxLength={255}
                        placeholder="Epic title"
                    />
                ) : (
                    <h1 className="text-2xl font-bold text-text-primary truncate flex-1 min-w-0">{epic.title}</h1>
                )}

                {/* Loop v1: which epics the current sprint works on. The
                    Conductor sets this too; a human can always override. */}
                {!editing && (
                    <select
                        aria-label="Epic status"
                        className="input w-auto text-sm"
                        value={epic.status || 'backlog'}
                        onChange={async (e) => {
                            try { setEpic(await api.updateEpic(epicId, { status: e.target.value })); }
                            catch (err) { alert('Could not change status: ' + (err.message || err)); }
                        }}
                    >
                        <option value="backlog">Parked</option>
                        <option value="in_progress">In this sprint</option>
                        <option value="done">Done</option>
                    </select>
                )}

                {editing ? (
                    <>
                        <button
                            onClick={handleSave}
                            disabled={saving || !form.title.trim()}
                            className="btn-primary px-4 py-2 rounded-xl text-sm font-bold flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
                            title="Save changes"
                        >
                            <Check className="w-4 h-4" /> {saving ? 'Saving…' : 'Save'}
                        </button>
                        <button
                            onClick={() => setEditing(false)}
                            disabled={saving}
                            className="btn-ghost px-4 py-2 rounded-xl text-sm font-medium flex items-center gap-1.5"
                            title="Cancel"
                        >
                            <X className="w-4 h-4" /> Cancel
                        </button>
                    </>
                ) : (
                    <>
                        <button
                            onClick={() => setShowPlan(true)}
                            className="btn-primary px-4 py-2 rounded-xl text-sm font-bold flex items-center gap-1.5"
                            title="Plan this epic with an agent"
                        >
                            <Sparkles className="w-4 h-4" /> Plan Epic
                        </button>
                        <button
                            onClick={startEdit}
                            className="flex items-center gap-1.5 px-3 py-2 rounded-xl hover:bg-bg-hover text-text-secondary text-sm font-medium"
                            title="Edit epic"
                        >
                            <Pencil className="w-4 h-4" /> Edit
                        </button>
                        <button
                            onClick={handleDelete}
                            className="p-2 rounded-xl hover:bg-bg-hover text-text-secondary hover:text-red-500"
                            title="Delete epic (tasks detached)"
                        >
                            <Trash2 className="w-4 h-4" />
                        </button>
                    </>
                )}
            </div>

            <div className="card max-h-72 overflow-y-auto flex-shrink-0">
                {editing ? (
                    <div className="flex flex-col gap-4">
                        <div>
                            <label className="block text-[11px] font-bold uppercase mb-2 text-text-tertiary tracking-wider">Description</label>
                            <textarea
                                className="input resize-none h-40 w-full"
                                value={form.description}
                                onChange={e => setForm({ ...form, description: e.target.value })}
                                placeholder="High-level goal or theme... (markdown supported)"
                            />
                        </div>
                        <div>
                            <label className="block text-[11px] font-bold uppercase mb-2 text-text-tertiary tracking-wider">Color Theme</label>
                            <div className="flex flex-wrap gap-2.5">
                                {EPIC_COLORS.map(c => (
                                    <button
                                        key={c}
                                        type="button"
                                        onClick={() => setForm({ ...form, color: c })}
                                        className={`w-8 h-8 rounded-full transition-transform hover:scale-110 active:scale-95 flex items-center justify-center ${form.color === c ? 'ring-2 ring-white ring-offset-2 ring-offset-bg-card' : ''}`}
                                        style={{ backgroundColor: c }}
                                    >
                                        {form.color === c && <div className="w-1.5 h-1.5 rounded-full bg-white shadow-sm" />}
                                    </button>
                                ))}
                            </div>
                        </div>
                    </div>
                ) : (
                    /* AP-39: render description as GitHub-flavored markdown
                       (tables, code, headings, lists) — not as plain text. */
                    epic.description
                        ? <Markdown>{epic.description}</Markdown>
                        : <span className="italic text-text-tertiary text-sm">No description.</span>
                )}
            </div>

            <div className="grid grid-cols-3 gap-4">
                <Stat label="Total" value={total} color="#5f6368" />
                <Stat label="In progress" value={inProgress} color="#7c4dff" />
                <Stat label="Done" value={`${done} / ${total}`} color="#2ecc71" />
            </div>

            <EpicAttachments
                epicId={epicId}
                attachments={attachments}
                onChange={loadAttachments}
            />

            <div className="card flex flex-col flex-1 min-h-0">
                <h2 className="text-lg font-semibold text-text-primary mb-3 flex items-center gap-2 flex-shrink-0">
                    <ListTodo className="w-5 h-5" /> Tasks
                </h2>
                {tasks.length === 0 ? (
                    <p className="text-sm text-text-tertiary">No tasks attached to this epic yet.</p>
                ) : (
                    <div className="space-y-1 overflow-y-auto flex-1 min-h-0">
                        {tasks.map(t => (
                            <button
                                key={t.id}
                                onClick={() => navigate(ROUTES.STUDIO_TASK(t.key || t.id))}
                                className="w-full flex items-center gap-3 px-3 py-2 rounded-md hover:bg-bg-hover text-left transition-colors"
                            >
                                <span
                                    className="w-2 h-2 rounded-full flex-shrink-0"
                                    style={{ backgroundColor: PRIORITY_DOTS[t.priority] || PRIORITY_DOTS.medium }}
                                />
                                <span className="text-[10px] font-mono text-text-tertiary flex-shrink-0">{t.key || t.id}</span>
                                <span className="text-sm text-text-primary flex-1 truncate">{t.title}</span>
                                <span
                                    className="text-xs px-1.5 py-0.5 rounded text-white font-medium flex-shrink-0"
                                    style={{ backgroundColor: STATUS_COLORS[t.status] || STATUS_COLORS.backlog }}
                                >
                                    {t.status?.replace('_', ' ')}
                                </span>
                            </button>
                        ))}
                    </div>
                )}
            </div>
            </div>

            {showPlan && (
                <PlanEpicModal
                    epic={epic}
                    onClose={() => setShowPlan(false)}
                    onStarted={(run) => navigate(ROUTES.FORGE_RUN(run.id))}
                />
            )}
        </div>
    );
}

function EpicAttachments({ epicId, attachments, onChange }) {
    const [uploading, setUploading] = useState(false);
    const handleUpload = async (e) => {
        const file = e.target.files?.[0];
        e.target.value = '';
        if (!file) return;
        setUploading(true);
        try {
            await api.uploadEpicAttachment(epicId, file);
            await onChange();
        } catch (err) {
            alert('Upload failed: ' + (err.message || err));
        } finally {
            setUploading(false);
        }
    };
    return (
        <div className="card flex-shrink-0">
            <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-semibold text-text-primary flex items-center gap-2">
                    <Paperclip className="w-4 h-4" /> Attachments
                </h2>
                <label className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg hover:bg-bg-hover text-text-secondary text-xs font-medium cursor-pointer">
                    <Upload className="w-3.5 h-3.5" /> {uploading ? 'Uploading…' : 'Upload'}
                    <input type="file" className="hidden" onChange={handleUpload} disabled={uploading} />
                </label>
            </div>
            {attachments.length === 0 ? (
                <p className="text-sm text-text-tertiary">No files attached.</p>
            ) : (
                <ul className="space-y-1">
                    {attachments.map(a => (
                        <li key={a.id} className="flex items-center gap-2 text-sm">
                            <button
                                onClick={() => api.downloadAttachment(a.id, a.filename)}
                                className="text-accent hover:underline truncate text-left"
                                title={a.filename}
                            >
                                {a.filename}
                            </button>
                            <span className="text-[10px] text-text-tertiary flex-shrink-0">
                                {Math.max(1, Math.round((a.size_bytes || 0) / 1024))} KB
                            </span>
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}

function PlanEpicModal({ epic, onClose, onStarted }) {
    const [agents, setAgents] = useState([]);
    const [agentId, setAgentId] = useState('');
    const [prompt, setPrompt] = useState('');
    const [loading, setLoading] = useState(true);
    const [starting, setStarting] = useState(false);
    const [error, setError] = useState(null);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const [ags, tpl] = await Promise.all([
                    api.forge.listAgents(),
                    api.getEpicPlanTemplate(epic.id),
                ]);
                if (cancelled) return;
                // Only agents bound to a runtime can actually run.
                const runnable = (Array.isArray(ags) ? ags : []).filter(a => a.runtime_id);
                setAgents(runnable);
                setAgentId(runnable[0]?.id || '');
                setPrompt(tpl?.prompt || '');
            } catch (err) {
                if (!cancelled) setError(err.message || 'Failed to load');
            } finally {
                if (!cancelled) setLoading(false);
            }
        })();
        return () => { cancelled = true; };
    }, [epic.id]);

    const handleStart = async () => {
        if (!agentId) return;
        setStarting(true);
        setError(null);
        try {
            const run = await api.planEpic(epic.id, { agent_id: agentId, prompt });
            onStarted(run);
        } catch (err) {
            setError(err.message || 'Failed to start planning run');
            setStarting(false);
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
            <div className="card w-full max-w-2xl flex flex-col gap-4" onClick={e => e.stopPropagation()}>
                <div className="flex items-center gap-2">
                    <Sparkles className="w-5 h-5 text-accent" />
                    <h2 className="text-lg font-bold text-text-primary">Plan epic: {epic.title}</h2>
                </div>
                <p className="text-sm text-text-tertiary -mt-2">
                    An agent will break this epic into board tasks. Pick the agent and tweak the request below.
                </p>
                {loading ? (
                    <div className="text-text-tertiary text-sm py-6 text-center">Loading…</div>
                ) : (
                    <>
                        <div>
                            <label className="block text-[11px] font-bold uppercase mb-2 text-text-tertiary tracking-wider">Agent</label>
                            {agents.length === 0 ? (
                                <p className="text-sm text-red-400">No runnable agent available. Bind an agent to a runtime first.</p>
                            ) : (
                                <select
                                    className="input w-full"
                                    value={agentId}
                                    onChange={e => setAgentId(e.target.value)}
                                >
                                    {agents.map(a => (
                                        <option key={a.id} value={a.id}>{a.name}</option>
                                    ))}
                                </select>
                            )}
                        </div>
                        <div>
                            <label className="block text-[11px] font-bold uppercase mb-2 text-text-tertiary tracking-wider">Planning request</label>
                            <textarea
                                className="input resize-none h-40 w-full"
                                value={prompt}
                                onChange={e => setPrompt(e.target.value)}
                                placeholder="What should the agent plan?"
                            />
                        </div>
                    </>
                )}
                {error && <p className="text-sm text-red-400">{error}</p>}
                <div className="flex justify-end gap-2">
                    <button onClick={onClose} className="btn-ghost px-4 py-2 rounded-xl text-sm font-medium">Cancel</button>
                    <button
                        onClick={handleStart}
                        disabled={loading || starting || !agentId}
                        className="btn-primary px-4 py-2 rounded-xl text-sm font-bold flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        <Sparkles className="w-4 h-4" /> {starting ? 'Starting…' : 'Start planning'}
                    </button>
                </div>
            </div>
        </div>
    );
}

function Stat({ label, value, color }) {
    return (
        <div className="card flex flex-col">
            <span className="text-xs uppercase tracking-wider text-text-tertiary mb-1">{label}</span>
            <span className="text-xl font-bold text-text-primary" style={{ color }}>{value}</span>
        </div>
    );
}
