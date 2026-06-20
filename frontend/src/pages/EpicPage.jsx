import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Pencil, Trash2, ListTodo, Check, X } from 'lucide-react';
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
                        placeholder="Epic title"
                    />
                ) : (
                    <h1 className="text-2xl font-bold text-text-primary truncate flex-1 min-w-0">{epic.title}</h1>
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
