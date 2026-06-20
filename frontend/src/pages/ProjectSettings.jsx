/**
 * Project Settings — edit project metadata in place on the project itself.
 *
 * Tabs:
 *   - General: name, description, primary repo path/url, conventions md.
 *   - Repos: add/remove repos via the AP-121 surface; mark one as primary.
 *
 * Lives at /studio/project/:projectId/settings so it inherits the
 * project's left-bar nav and breadcrumbs, per the rule "settings live
 * with the entity."
 */

import React, { useEffect, useState } from 'react';
import { useParams, useLocation } from 'react-router-dom';
import {
    Folder, GitBranch, Save, Plus, Trash2, Star, Settings as SettingsIcon,
    Link2, Pencil, Check, X, AlertTriangle, ChevronDown,
} from 'lucide-react';
import { api } from '../api';


export function ProjectSettings() {
    const { projectId } = useParams();
    const location = useLocation();
    const initialTab = location.hash === '#repos' ? 'repos' : 'general';
    const [tab, setTab] = useState(initialTab);

    return (
        <div className="flex-1 overflow-y-auto">
            <div className="max-w-3xl mx-auto p-6 space-y-4">
                <div className="flex items-center gap-3">
                    <SettingsIcon className="w-5 h-5 text-text-secondary" />
                    <h2 className="text-xl font-semibold text-text-primary">
                        Project Settings
                    </h2>
                </div>

                <div className="flex gap-2 border-b border-border-subtle">
                    <TabButton active={tab === 'general'}
                        onClick={() => setTab('general')}
                        label="General" />
                    <TabButton active={tab === 'repos'}
                        onClick={() => setTab('repos')}
                        label="Repos" />
                </div>

                {tab === 'general' && <GeneralTab projectId={projectId} />}
                {tab === 'repos' && <ReposTab projectId={projectId} />}
            </div>
        </div>
    );
}


function TabButton({ active, onClick, label }) {
    return (
        <button onClick={onClick}
            className={`px-4 py-2 -mb-px border-b-2 transition-colors text-sm font-medium ${
                active
                    ? 'border-accent-primary text-accent-primary'
                    : 'border-transparent text-text-secondary hover:text-text-primary'
            }`}>
            {label}
        </button>
    );
}


// ── General ──────────────────────────────────────────────────────────

function GeneralTab({ projectId }) {
    const [project, setProject] = useState(null);
    const [form, setForm] = useState(null);
    const [saving, setSaving] = useState(false);
    const [msg, setMsg] = useState('');

    useEffect(() => {
        api.getProject(projectId).then((p) => {
            setProject(p);
            setForm({
                name: p.name || '',
                description: p.description || '',
                repo_path: p.repo_path || '',
                repo_url: p.repo_url || '',
                conventions_md: p.conventions_md || '',
                work_signal: p.work_signal || 'working_tree',
                sandbox_mode: p.sandbox_mode || '',  // '' = inherit from agent
                gates_enabled: !!p.gates_enabled,  // AP-158
            });
        }).catch(() => setProject(null));
    }, [projectId]);

    if (!form) return <div className="text-text-tertiary text-sm">Loading…</div>;

    const dirty = project && (
        form.name !== (project.name || '')
        || form.description !== (project.description || '')
        || form.repo_path !== (project.repo_path || '')
        || form.repo_url !== (project.repo_url || '')
        || form.conventions_md !== (project.conventions_md || '')
        || form.work_signal !== (project.work_signal || 'working_tree')
        || form.sandbox_mode !== (project.sandbox_mode || '')
        || form.gates_enabled !== !!project.gates_enabled
    );

    const save = async () => {
        setSaving(true);
        setMsg('');
        try {
            const updated = await api.updateProject(projectId, {
                name: form.name,
                description: form.description,
                repo_path: form.repo_path || null,
                repo_url: form.repo_url || null,
                conventions_md: form.conventions_md || null,
                work_signal: form.work_signal || null,
                // AP-155: send the literal empty string to clear an
                // override back to "inherit from agent". null means
                // "don't change" in the PATCH; "" is the explicit
                // clear value the backend recognizes.
                sandbox_mode: form.sandbox_mode,
                gates_enabled: form.gates_enabled,
            });
            setProject(updated);
            setMsg('Saved');
            setTimeout(() => setMsg(''), 2000);
        } catch (err) {
            setMsg('Error: ' + (err.message || err));
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="space-y-4">
            <Field label="Name">
                <input className="input" value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </Field>
            <Field label="Description">
                <textarea className="input" rows="2" value={form.description}
                    onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </Field>
            <Field label="Primary repo path"
                hint="Absolute filesystem path the daemon worktrees off (same-machine default).">
                <input className="input" placeholder="/path/to/repo"
                    value={form.repo_path}
                    onChange={(e) => setForm({ ...form, repo_path: e.target.value })} />
            </Field>
            <Field label="Primary repo URL"
                hint="Optional — daemon clones from here when repo_path isn't accessible.">
                <input className="input" placeholder="https://github.com/org/repo.git"
                    value={form.repo_url}
                    onChange={(e) => setForm({ ...form, repo_url: e.target.value })} />
            </Field>
            <Field label="Conventions (markdown)"
                hint="Materialized as .agentira/CONVENTIONS.md in the agent workdir.">
                <textarea className="input font-mono text-xs" rows="6"
                    value={form.conventions_md}
                    placeholder={'# Conventions\nUse ruff. All commits on a feature branch.'}
                    onChange={(e) => setForm({ ...form, conventions_md: e.target.value })} />
            </Field>
            <Field label="Run detection (work signal)"
                hint="When a chat turn in a task counts as work and becomes a tracked run. 'Working tree' is the most thorough — nothing the agent touches is lost.">
                <select className="input" value={form.work_signal}
                    onChange={(e) => setForm({ ...form, work_signal: e.target.value })}>
                    <option value="working_tree">Working tree — any tracked change or new untracked file (default)</option>
                    <option value="tracked">Tracked changes only — edits to tracked files</option>
                    <option value="committed">Committed only — a new commit</option>
                </select>
            </Field>
            <Field label="Sandbox (project override)"
                hint="Containment level for runs in this project. Overrides each agent's own setting. Leave blank to inherit. Phase 1: backend logs the resolved mode; per-adapter enforcement lands next.">
                <select className="input" value={form.sandbox_mode}
                    onChange={(e) => setForm({ ...form, sandbox_mode: e.target.value })}>
                    <option value="">(inherit from agent)</option>
                    <option value="off">Off — cwd set, nothing enforced</option>
                    <option value="cwd">cwd — claude --add-dir / --disallowedTools (best-effort)</option>
                    <option value="strict">strict — OS sandbox (bwrap / sandbox-exec)</option>
                    <option value="container">container — per-agent Docker (strongest)</option>
                </select>
            </Field>
            <Field label="Gated transitions (AP-158)"
                hint={
                    "Block column moves when evidence is missing — DoD on the task, assignee, branch/PR linked, all DoD items checked before done. Off by default; turn on for strict workflows."
                }>
                <label className="flex items-center gap-2 text-sm text-text-secondary cursor-pointer">
                    <input
                        type="checkbox"
                        checked={form.gates_enabled}
                        onChange={(e) => setForm({ ...form, gates_enabled: e.target.checked })}
                    />
                    Enforce column-exit gates on this project
                </label>
            </Field>
            <div className="flex items-center gap-3">
                <button className="btn btn-primary" onClick={save}
                    disabled={!dirty || saving}>
                    <Save className="w-4 h-4" />
                    {saving ? 'Saving…' : 'Save'}
                </button>
                {msg && (
                    <span className={`text-xs ${msg.startsWith('Error') ? 'text-red-400' : 'text-text-secondary'}`}>
                        {msg}
                    </span>
                )}
            </div>
        </div>
    );
}


// ── Repos ────────────────────────────────────────────────────────────

function ReposTab({ projectId }) {
    const [repos, setRepos] = useState(null);
    const [busy, setBusy] = useState('');
    const [msg, setMsg] = useState('');

    const reload = async () => {
        const r = await api.listProjectRepos(projectId).catch(() => []);
        setRepos(r);
    };
    useEffect(() => { reload(); }, [projectId]);

    if (repos === null) return <div className="text-text-tertiary text-sm">Loading…</div>;

    const add = async (data) => {
        setBusy('add');
        setMsg('');
        try {
            await api.addProjectRepo(projectId, data);
            await reload();
        } catch (err) {
            setMsg('Add failed: ' + (err.message || err));
        } finally {
            setBusy('');
        }
    };

    const remove = async (name) => {
        if (!confirm(`Detach repo "${name}" from this project?`)) return;
        setBusy(name);
        try {
            await api.removeProjectRepo(projectId, name);
            await reload();
        } catch (err) {
            setMsg('Remove failed: ' + (err.message || err));
        } finally {
            setBusy('');
        }
    };

    const update = async (name, data) => {
        setBusy(name);
        setMsg('');
        try {
            await api.updateProjectRepo(projectId, name, data);
            await reload();
        } catch (err) {
            setMsg('Update failed: ' + (err.message || err));
        } finally {
            setBusy('');
        }
    };

    return (
        <div className="space-y-4">
            <p className="text-xs text-text-secondary">
                Attach git repos so tasks can target the right codebase.
                The primary repo is the default when a task doesn't specify
                a <code className="text-text-primary">repo_name</code>.
            </p>
            <p className="text-xs text-text-tertiary">
                Set a <strong className="text-text-secondary">git remote URL</strong> on
                a repo and the daemon clones it into its own workspace
                (<code className="text-text-primary">~/.agentira/sources</code>) — it
                never touches your local folders. This is required for repos under
                Desktop / Documents / Downloads, which macOS blocks the daemon from
                reading.
            </p>

            {repos.length === 0 ? (
                <div className="card text-text-tertiary text-sm">
                    No repos attached yet.
                </div>
            ) : (
                <div className="space-y-2">
                    {repos.map((r) => (
                        <RepoRow key={r.id || r.name} repo={r}
                            onRemove={() => remove(r.name)}
                            onUpdate={(data) => update(r.name, data)}
                            busy={busy === r.name} />
                    ))}
                </div>
            )}

            <AddRepoForm onSubmit={add} busy={busy === 'add'} />

            {msg && (
                <div className={`text-xs ${msg.startsWith('Add') || msg.startsWith('Remove') ? 'text-red-400' : 'text-text-secondary'}`}>
                    {msg}
                </div>
            )}
        </div>
    );
}


function RepoRow({ repo, onRemove, onUpdate, busy }) {
    const [editing, setEditing] = useState(false);
    const [url, setUrl] = useState(repo.repo_url || '');

    const commit = () => {
        const next = url.trim();
        setEditing(false);
        if (next === (repo.repo_url || '')) return;   // no-op
        onUpdate({ repo_url: next });
    };
    const cancel = () => { setUrl(repo.repo_url || ''); setEditing(false); };

    return (
        <div className="card flex items-center gap-3">
            <Folder className="w-4 h-4 text-text-secondary flex-shrink-0" />
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                    <div className="text-sm font-medium text-text-primary">{repo.name}</div>
                    {repo.is_primary && (
                        <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-accent-subtle text-accent-primary flex items-center gap-1">
                            <Star className="w-3 h-3" /> primary
                        </span>
                    )}
                    {repo.repo_url ? (
                        <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-green-500/15 text-green-500 flex items-center gap-1"
                            title="Daemon clones this remote into its own workspace">
                            <Link2 className="w-3 h-3" /> git remote
                        </span>
                    ) : (
                        <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-bg-hover text-text-tertiary"
                            title="No remote — daemon worktrees off the local path (blocked under Desktop/Documents/Downloads)">
                            local only
                        </span>
                    )}
                </div>
                {repo.repo_path && (
                    <div className="text-xs text-text-tertiary font-mono truncate">{repo.repo_path}</div>
                )}
                {/* AP-197: inline-editable git remote URL */}
                {editing ? (
                    <div className="flex items-center gap-1 mt-1">
                        <input autoFocus value={url} onChange={(e) => setUrl(e.target.value)}
                            onKeyDown={(e) => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') cancel(); }}
                            placeholder="https://github.com/org/repo"
                            className="input text-xs py-1 px-2 flex-1 font-mono" />
                        <button onClick={commit} className="p-0.5 text-green-500" title="Save"><Check className="w-3.5 h-3.5" /></button>
                        <button onClick={cancel} className="p-0.5 text-text-tertiary" title="Cancel"><X className="w-3.5 h-3.5" /></button>
                    </div>
                ) : (
                    <button onClick={() => setEditing(true)}
                        className="flex items-center gap-1 text-xs text-text-tertiary hover:text-text-secondary mt-0.5 font-mono truncate max-w-full"
                        title="Set the git remote so the daemon clones it">
                        <Pencil className="w-3 h-3 flex-shrink-0" />
                        <span className="truncate">{repo.repo_url || 'Connect git remote…'}</span>
                    </button>
                )}
                {repo.default_branch && repo.default_branch !== 'main' && (
                    <div className="text-[10px] text-text-tertiary mt-0.5">
                        default branch: {repo.default_branch}
                    </div>
                )}
                <FreshnessControl
                    value={repo.worktree_freshness || 'always_latest'}
                    baseBranch={repo.default_branch || 'main'}
                    busy={busy}
                    onChange={(v) => onUpdate({ worktree_freshness: v })}
                />
            </div>
            <button onClick={onRemove} disabled={busy}
                className="btn btn-ghost text-red-400 hover:bg-red-500/10"
                title="Detach this repo from the project">
                <Trash2 className="w-4 h-4" />
            </button>
        </div>
    );
}


// How worktrees start relative to the base branch. Git terms straight up —
// fuller explanations belong in a tooltip later, not in invented analogies.
// (danger = builds on a stale base; warn before allowing it.)
const FRESHNESS = {
    always_latest: {
        label: (b) => `Branch from latest origin/${b}, rebase on resume`,
        danger: false,
    },
    new_only: {
        label: (b) => `Branch from latest origin/${b}; don't rebase existing branches`,
        danger: true,
    },
    pinned: {
        label: () => `Pinned — branch from local HEAD, no fetch/rebase`,
        danger: true,
    },
};

function FreshnessControl({ value, baseBranch, busy, onChange }) {
    const [open, setOpen] = useState(false);
    const cfg = FRESHNESS[value] || FRESHNESS.always_latest;

    return (
        <div className="mt-2 text-xs">
            <button type="button" onClick={() => setOpen((s) => !s)}
                className={`flex items-center gap-1.5 ${cfg.danger ? 'text-yellow-500' : 'text-green-500'} hover:opacity-80`}>
                {cfg.danger ? <AlertTriangle className="w-3.5 h-3.5" /> : <GitBranch className="w-3.5 h-3.5" />}
                <span className="font-mono">{cfg.label(baseBranch)}</span>
                <ChevronDown className={`w-3 h-3 transition-transform ${open ? '' : '-rotate-90'}`} />
            </button>
            {open && (
                <div className="mt-1.5 pl-1 space-y-1.5">
                    {Object.entries(FRESHNESS).map(([key, c]) => (
                        <label key={key} className="flex items-start gap-2 cursor-pointer">
                            <input type="radio" name={`fresh-${baseBranch}`} className="mt-0.5"
                                checked={value === key} disabled={busy}
                                onChange={() => value !== key && onChange(key)} />
                            <span className={`font-mono ${c.danger ? 'text-yellow-300/90' : 'text-text-secondary'}`}>
                                {c.label(baseBranch)}
                            </span>
                        </label>
                    ))}
                    {cfg.danger && (
                        <div className="bg-yellow-500/10 border border-yellow-500/20 rounded p-2 text-yellow-300/90">
                            Builds on a stale base — agents may work off outdated code. Use on purpose.
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}


function AddRepoForm({ onSubmit, busy }) {
    const [name, setName] = useState('');
    const [repoPath, setRepoPath] = useState('');
    const [repoUrl, setRepoUrl] = useState('');
    const [defaultBranch, setDefaultBranch] = useState('main');
    const [isPrimary, setIsPrimary] = useState(false);

    const submit = async (e) => {
        e.preventDefault();
        if (!name.trim() || (!repoPath.trim() && !repoUrl.trim())) return;
        await onSubmit({
            name: name.trim(),
            repo_path: repoPath.trim(),
            repo_url: repoUrl.trim(),
            default_branch: defaultBranch.trim() || 'main',
            is_primary: isPrimary,
        });
        setName(''); setRepoPath(''); setRepoUrl('');
        setDefaultBranch('main'); setIsPrimary(false);
    };

    return (
        <form onSubmit={submit} className="card space-y-3 border border-dashed">
            <div className="flex items-center gap-2 text-sm font-medium text-text-primary">
                <Plus className="w-4 h-4" /> Attach a repo
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <Field label="Name" hint="Short identifier — e.g. 'backend', 'frontend'.">
                    <input className="input" value={name}
                        onChange={(e) => setName(e.target.value)}
                        placeholder="backend" />
                </Field>
                <Field label="Default branch">
                    <input className="input" value={defaultBranch}
                        onChange={(e) => setDefaultBranch(e.target.value)}
                        placeholder="main" />
                </Field>
                <Field label="Repo path">
                    <input className="input" value={repoPath}
                        onChange={(e) => setRepoPath(e.target.value)}
                        placeholder="/path/to/repo" />
                </Field>
                <Field label="Repo URL">
                    <input className="input" value={repoUrl}
                        onChange={(e) => setRepoUrl(e.target.value)}
                        placeholder="https://github.com/org/repo.git" />
                </Field>
            </div>
            <label className="flex items-center gap-2 text-xs text-text-secondary cursor-pointer">
                <input type="checkbox" checked={isPrimary}
                    onChange={(e) => setIsPrimary(e.target.checked)} />
                Mark as primary (tasks without an explicit repo_name target this one)
            </label>
            <button type="submit" className="btn btn-primary"
                disabled={busy || !name.trim() || (!repoPath.trim() && !repoUrl.trim())}>
                <Plus className="w-4 h-4" />
                {busy ? 'Attaching…' : 'Attach repo'}
            </button>
        </form>
    );
}


function Field({ label, hint, children }) {
    return (
        <div>
            <label className="block text-xs text-text-tertiary mb-1">{label}</label>
            {children}
            {hint && <p className="text-xs text-text-tertiary mt-1">{hint}</p>}
        </div>
    );
}
