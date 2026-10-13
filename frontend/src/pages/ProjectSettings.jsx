/**
 * Project Settings — edit a project in place, laid out like account Settings:
 * a section list on the left, one focused section on the right.
 *
 *   Overview            name, description, goals, conventions
 *   Repositories        attached repos, default repo location, where agents work
 *   Checks & workflow   the command that proves the work, gates, run detection
 *   Safety & isolation  sandbox level, per-run environment
 *   Danger zone         delete the project
 *
 * Every project field shares one form and one Save, so a change in any section
 * is saved the same way. Repo attach/detach/token actions apply immediately.
 *
 * Lives at /studio/project/:projectId/settings so it inherits the project's
 * left-bar nav and breadcrumbs, per the rule "settings live with the entity."
 */

import React, { useEffect, useRef, useState } from 'react';
import { useParams, useLocation, useNavigate } from 'react-router-dom';
import {
    Folder, Plus, Trash2, Star, Link2, Pencil, Check, X,
    AlertTriangle,
} from 'lucide-react';
import { api } from '../api';
import { ROUTES } from '../routes';
import { ConfirmModal } from '../components/ConfirmModal';
import { parseGitAddress, fetchRepoInfo } from '../lib/gitAddress';
import { GitTokenField } from '../components/GitTokenField';
import {
    SettingsSection, SubLabel, Field, TextField, TextArea, Toggle, ChoiceList,
    Card, Notice, Button, Advanced, InfoTip,
} from '../components/settings/controls';


// ── Option lists (plain labels first; technical detail in help/Advanced) ──────

const WORK_SIGNALS = [
    { value: 'working_tree', label: 'Any change in the working folder (recommended)',
      help: 'Edits, new files and commits all count as work. Nothing an agent touches is lost.' },
    { value: 'tracked', label: 'Edits to existing files only',
      help: 'New files an agent creates are ignored until they are tracked.' },
    { value: 'committed', label: 'Saved commits only',
      help: 'A chat turn only counts once the agent commits.' },
];

const SANDBOX_MODES = [
    { value: '', label: 'Use each agent’s own setting (default)',
      help: 'No project-wide rule; every agent keeps the containment it was configured with.' },
    { value: 'off', label: 'None',
      help: 'Agents start in the project folder and nothing is enforced.' },
    { value: 'cwd', label: 'Stay in the project folder (best effort)',
      help: 'Agents are asked not to touch files outside the project. Not a hard guarantee.' },
    { value: 'strict', label: 'Locked to the project folder',
      help: 'The operating system blocks access outside the project.' },
    { value: 'container', label: 'Own container per agent (strongest)',
      help: 'Each agent runs in its own Docker container, fully separated from your machine.' },
];

const ENV_ISOLATION = [
    { value: 'auto', label: 'Automatic (recommended)',
      help: 'Agentira picks the safest, cheapest isolation for this project.' },
    { value: 'hermetic', label: 'No shared services',
      help: "Runs use a clean, empty environment. Best when tests don't need a live database." },
    { value: 'per_run_db', label: 'Separate database for each run',
      help: 'Each run gets its own throwaway database so agents never share data. Needs a setup command (Advanced).' },
    { value: 'per_run_compose', label: 'Separate full stack for each run',
      help: 'Each run gets its own set of services (docker compose). Heaviest, strongest isolation.' },
];

const FRESHNESS = [
    { value: 'always_latest', label: 'Start from the latest code and keep branches up to date',
      help: 'New branches start from the newest remote code; resumed branches are rebased onto it.' },
    { value: 'new_only', label: 'Start from the latest code, leave existing branches alone',
      help: 'Resumed branches can fall behind. Use on purpose.', tone: 'warn' },
    { value: 'pinned', label: 'Use the code already on this machine',
      help: 'No fetching or rebasing — agents may work from outdated code. Use on purpose.', tone: 'warn' },
];

const toForm = (p) => ({
    name: p.name || '',
    description: p.description || '',
    repo_path: p.repo_path || '',
    repo_url: p.repo_url || '',
    conventions_md: p.conventions_md || '',
    verify_cmd: p.verify_cmd || '',
    direction_md: p.direction_md || '',
    verify_timeout_minutes: p.verify_timeout_minutes || 30,
    work_signal: p.work_signal || 'working_tree',
    sandbox_mode: p.sandbox_mode || '',          // '' = inherit from agent
    env_isolation: p.env_isolation || 'auto',    // '' stored = auto
    env_setup_cmd: p.env_setup_cmd || '',
    env_teardown_cmd: p.env_teardown_cmd || '',
    env_db_admin_url: p.env_db_admin_url || '',
    gates_enabled: !!p.gates_enabled,
    workflow_enabled: !!p.workflow_enabled,
    workspace_kind: p.workspace_kind || '',
});

const isDirty = (form, project) => !!project && JSON.stringify({
    ...form, verify_timeout_minutes: Number(form.verify_timeout_minutes),
}) !== JSON.stringify(toForm(project));


// ── Page shell ───────────────────────────────────────────────────────────────

const SECTIONS = [
    { id: 'overview', label: 'Overview' },
    { id: 'repos', label: 'Repositories' },
    { id: 'checks', label: 'Checks & workflow' },
    { id: 'safety', label: 'Safety & isolation' },
];

function NavSection({ label, children }) {
    return (
        <div style={{ marginBottom: 4 }}>
            <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.1em', color: 'var(--text-muted)', padding: '0 8px 10px' }}>
                {label}
            </div>
            {children}
        </div>
    );
}

function NavItem({ active, onClick, danger, children }) {
    return (
        <div role="button" tabIndex={0} onClick={onClick}
            onKeyDown={(e) => { if (e.key === 'Enter') onClick(); }}
            style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '7px 10px', borderRadius: 9, marginBottom: 2, fontSize: 13, cursor: 'pointer',
                color: danger ? '#f87171' : active ? 'var(--text-primary)' : 'var(--text-muted)',
                background: active ? 'var(--bg-hover,var(--surface-hover))' : 'transparent',
            }}>
            {children}
        </div>
    );
}

export function ProjectSettings() {
    const { projectId } = useParams();
    const location = useLocation();
    const [section, setSection] = useState(location.hash === '#repos' ? 'repos' : 'overview');
    const [project, setProject] = useState(null);
    const [form, setForm] = useState(null);
    const [repos, setRepos] = useState(null);
    const [saving, setSaving] = useState(false);
    const [msg, setMsg] = useState('');

    useEffect(() => {
        api.getProject(projectId).then((p) => {
            setProject(p);
            setForm(toForm(p));
        }).catch(() => setProject(null));
    }, [projectId]);

    const reloadRepos = async () => setRepos(await api.listProjectRepos(projectId).catch(() => []));
    useEffect(() => { reloadRepos(); }, [projectId]);

    if (!form) {
        return <div style={{ padding: 32, textAlign: 'center', fontSize: 13, color: 'var(--text-muted)' }}>Loading…</div>;
    }

    const set = (key) => (value) => setForm((f) => ({ ...f, [key]: value }));
    const bind = (key) => ({ value: form[key], onChange: (e) => set(key)(e.target.value) });
    const dirty = isDirty(form, project);

    const save = async () => {
        setSaving(true);
        setMsg('');
        try {
            const updated = await api.updateProject(projectId, {
                name: form.name,
                description: form.description,
                // "" clears; null would mean "don't change", so a field could
                // never be emptied.
                repo_path: form.repo_path,
                repo_url: form.repo_url,
                conventions_md: form.conventions_md,
                verify_cmd: form.verify_cmd,
                direction_md: form.direction_md,
                verify_timeout_minutes: Number(form.verify_timeout_minutes) || 30,
                work_signal: form.work_signal || null,
                // "" is the explicit clear back to "inherit from agent".
                sandbox_mode: form.sandbox_mode,
                // "auto" round-trips as "" (the backend stores NULL).
                env_isolation: form.env_isolation === 'auto' ? '' : form.env_isolation,
                env_setup_cmd: form.env_setup_cmd,
                env_teardown_cmd: form.env_teardown_cmd,
                env_db_admin_url: form.env_db_admin_url,
                gates_enabled: form.gates_enabled,
                workflow_enabled: form.workflow_enabled,
                workspace_kind: form.workspace_kind,
            });
            setProject(updated);
            setForm(toForm(updated));
            setMsg('saved');
            setTimeout(() => setMsg(''), 2000);
        } catch (err) {
            setMsg('Error: ' + (err.message || err));
        } finally {
            setSaving(false);
        }
    };

    const saveBar = (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 12, marginTop: 24 }}>
            {msg === 'saved' && <span style={{ fontSize: 12, color: '#4ade80' }}>Changes saved.</span>}
            {msg.startsWith('Error') && <span style={{ fontSize: 12, color: '#f87171' }}>{msg}</span>}
            {dirty && !msg && <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Unsaved changes</span>}
            <Button onClick={save} disabled={!dirty || saving}>
                {saving ? 'Saving…' : 'Save changes'}
            </Button>
        </div>
    );

    return (
        <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
            <aside style={{ width: 200, flexShrink: 0, borderRight: '1px solid var(--border-default)', background: 'var(--bg-card,var(--surface-nav))', padding: '20px 12px', overflowY: 'auto' }}>
                <NavSection label="PROJECT SETTINGS">
                    {SECTIONS.map((s) => (
                        <NavItem key={s.id} active={section === s.id} onClick={() => setSection(s.id)}>
                            {s.label}
                        </NavItem>
                    ))}
                    <NavItem active={section === 'danger'} danger onClick={() => setSection('danger')}>
                        Danger zone
                    </NavItem>
                </NavSection>
            </aside>

            <div style={{ flex: 1, overflowY: 'auto', padding: '24px 28px' }}>
                {section === 'overview' && (
                    <SettingsSection title="Overview"
                        description="What this project is, where it’s heading, and the rules agents follow in it.">
                        <Field label="Project name" htmlFor="ps-name">
                            <TextField id="ps-name" {...bind('name')} />
                        </Field>
                        <Field label="Description" htmlFor="ps-desc"
                            hint="Shown at the top of the project.">
                            <TextArea id="ps-desc" rows={6} {...bind('description')} />
                        </Field>
                        <Field label="Goals & direction" htmlFor="ps-direction"
                            hint="What this project is for and what matters most right now, in plain words. The Conductor plans each sprint from this — and may draft it if it's empty.">
                            <TextArea id="ps-direction" rows={5}
                                placeholder="e.g. Make the agent loop run on its own before any UI work."
                                {...bind('direction_md')} />
                        </Field>
                        <Field label="Conventions" htmlFor="ps-conventions"
                            hint="Markdown. Agents read it as .agentira/CONVENTIONS.md in their working folder.">
                            <TextArea id="ps-conventions" rows={6} mono
                                placeholder={'# Conventions\nUse ruff. All commits on a feature branch.'}
                                {...bind('conventions_md')} />
                        </Field>
                        {saveBar}
                    </SettingsSection>
                )}

                {section === 'repos' && (
                    <SettingsSection title="Repositories"
                        description="The code agents work on.">
                        <ReposList projectId={projectId} project={project} repos={repos} reload={reloadRepos} />
                        <Advanced label="Advanced">
                            <Toggle id="ps-own-folder"
                                checked={form.workspace_kind === 'local_folder'}
                                onChange={(on) => set('workspace_kind')(on ? 'local_folder' : '')}
                                label="Work directly in my own folder"
                                hint="Normally each agent gets its own fresh copy of the repo, so your folder is never touched. Turn this on to have agents edit the repo folder on this machine directly instead. Only works for folders the daemon can read — macOS blocks Desktop, Documents and Downloads." />
                        </Advanced>
                        {saveBar}
                    </SettingsSection>
                )}

                {section === 'checks' && (
                    <SettingsSection title="Checks & workflow"
                        description="How work is proven before it ships, and how strictly it moves through the board.">
                        <SubLabel>PROOF BEFORE MERGE</SubLabel>
                        <Field label="Command that proves the project works" htmlFor="ps-verify"
                            hint="Runs on the merged code before anything is pushed. If it fails, the work goes back to the agent with the output. Leave empty and merges are refused.">
                            <TextField id="ps-verify" mono placeholder="e.g. make test" {...bind('verify_cmd')} />
                        </Field>
                        <Field label="Time limit for that command (minutes)" htmlFor="ps-verify-timeout">
                            <TextField id="ps-verify-timeout" type="number" min="1" max="240" style={{ width: 120 }} {...bind('verify_timeout_minutes')} />
                        </Field>

                        <SubLabel>BOARD RULES</SubLabel>
                        <Toggle id="ps-gates" checked={form.gates_enabled} onChange={set('gates_enabled')}
                            label="Require evidence before a task moves on"
                            hint="Blocks column moves until the task has a definition of done, an assignee, a linked branch or PR, and every done-item checked. Off by default; turn on for strict workflows." />
                        <Toggle id="ps-workflow" checked={form.workflow_enabled} onChange={set('workflow_enabled')}
                            label="Run automation workflow on this project"
                            hint="Master switch. When off, no automatic task moves, hand-offs or follow-up runs happen — tasks only move when you move them." />

                        <SubLabel hint="When a chat turn on a task counts as work and becomes a tracked run.">RUN DETECTION</SubLabel>
                        <ChoiceList name="work_signal" value={form.work_signal} onChange={set('work_signal')} options={WORK_SIGNALS} />
                        {saveBar}
                    </SettingsSection>
                )}

                {section === 'safety' && (
                    <SettingsSection title="Safety & isolation"
                        description="How tightly agents are contained, and whether concurrent runs share an environment.">
                        <SubLabel hint="Overrides each agent’s own setting for runs in this project.">CONTAINMENT</SubLabel>
                        <ChoiceList name="sandbox_mode" value={form.sandbox_mode} onChange={set('sandbox_mode')} options={SANDBOX_MODES} />

                        <SubLabel hint="Forks the environment a run’s commands hit, so concurrent runs can’t collide on a shared dev stack.">RUN ENVIRONMENT</SubLabel>
                        <ChoiceList name="env_isolation" value={form.env_isolation} onChange={set('env_isolation')} options={ENV_ISOLATION} />
                        <EnvAdvanced form={form} bind={bind} />
                        {saveBar}
                    </SettingsSection>
                )}

                {section === 'danger' && (
                    <DangerZone projectId={projectId} projectName={project?.name} />
                )}
            </div>
        </div>
    );
}


// ── Repositories ─────────────────────────────────────────────────────────────

function ReposList({ projectId, project, repos, reload }) {
    const [busy, setBusy] = useState('');
    const [err, setErr] = useState('');

    if (repos === null) return <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Loading…</div>;

    const run = async (key, label, fn) => {
        setBusy(key);
        setErr('');
        try {
            await fn();
            await reload();
        } catch (e) {
            setErr(`${label} failed: ${e.message || e}`);
        } finally {
            setBusy('');
        }
    };

    const remove = (name) => {
        if (!confirm(`Detach repo "${name}" from this project?`)) return;
        run(name, 'Remove', () => api.removeProjectRepo(projectId, name));
    };

    // Older projects stored one repo on the project itself. It still works,
    // but it never shows in the list — offer to turn it into a real repo.
    const legacy = repos.length === 0 && (project?.repo_url || project?.repo_path);

    return (
        <>
            {repos.length === 0 && !legacy && (
                <Card style={{ fontSize: 12.5, color: 'var(--text-muted)', fontStyle: 'italic', textAlign: 'center' }}>
                    No repos attached yet.
                </Card>
            )}
            {legacy && (
                <Card>
                    <div style={{ fontSize: 13, color: 'var(--text-primary)' }}>
                        This project uses an older single-repo setup
                        <InfoTip>The repo was saved on the project itself instead of in this list. It still works. Convert it to manage its access token and branch handling here.</InfoTip>
                    </div>
                    <div style={{ fontSize: 11.5, color: 'var(--text-muted)', fontFamily: 'ui-monospace,monospace', margin: '6px 0 12px', wordBreak: 'break-all' }}>
                        {project.repo_url || project.repo_path}
                    </div>
                    <Button variant="secondary" disabled={busy === 'legacy'}
                        onClick={() => run('legacy', 'Convert', () => api.addProjectRepo(projectId, {
                            name: 'main', repo_url: project.repo_url || '', repo_path: project.repo_path || '',
                            default_branch: 'main', is_primary: true,
                        }))}>
                        {busy === 'legacy' ? 'Converting…' : 'Convert to a repo'}
                    </Button>
                </Card>
            )}
            {repos.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    {repos.map((r) => (
                        <RepoRow key={r.id || r.name} repo={r} projectId={projectId}
                            busy={busy === r.name} onReload={reload}
                            onRemove={() => remove(r.name)}
                            onUpdate={(data) => run(r.name, 'Update', () => api.updateProjectRepo(projectId, r.name, data))} />
                    ))}
                </div>
            )}
            <div style={{ marginTop: 12 }}>
                <AddRepoForm busy={busy === 'add'} hasRepos={repos.length > 0}
                    onSubmit={(data) => run('add', 'Add', () => api.addProjectRepo(projectId, data))} />
            </div>
            {err && <div style={{ marginTop: 10 }}><Notice tone="error">{err}</Notice></div>}
        </>
    );
}

const badge = (color, bg) => ({
    display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 10, fontWeight: 700,
    letterSpacing: '.06em', textTransform: 'uppercase', padding: '2px 7px', borderRadius: 6, color, background: bg,
});

function RepoRow({ repo, projectId, onReload, onRemove, onUpdate, busy }) {
    const [editing, setEditing] = useState(false);
    const [url, setUrl] = useState(repo.repo_url || '');

    const commit = () => {
        const next = url.trim();
        setEditing(false);
        if (next === (repo.repo_url || '')) return;
        onUpdate({ repo_url: next });
    };
    const cancel = () => { setUrl(repo.repo_url || ''); setEditing(false); };

    return (
        <Card>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 11 }}>
                <Folder style={{ width: 16, height: 16, marginTop: 2, color: 'var(--text-muted)', flexShrink: 0 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>{repo.name}</span>
                        {repo.is_primary && (
                            <span style={badge('var(--accent-primary)', 'var(--accent-subtle)')}><Star style={{ width: 10, height: 10 }} /> default</span>
                        )}
                        {!repo.repo_url && (
                            <span style={badge('var(--text-muted)', 'var(--surface-hover)')}>local only</span>
                        )}
                        <InfoTip>
                            {repo.is_primary ? 'The default repo is used for tasks that don’t name one. ' : ''}
                            {repo.repo_url
                                ? 'Connected to a git address: agents clone it into their own workspace and never touch your folders.'
                                : 'No git address yet, so agents branch from a folder on this machine. Add the address below — macOS blocks agents from reading Desktop, Documents and Downloads.'}
                        </InfoTip>
                    </div>
                    {editing ? (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 8 }}>
                            <TextField autoFocus mono value={url} placeholder="https://github.com/org/repo"
                                onChange={(e) => setUrl(e.target.value)}
                                onKeyDown={(e) => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') cancel(); }} />
                            <Button variant="secondary" aria-label="Save address" onClick={commit} icon={Check} style={{ padding: '9px 10px' }} />
                            <Button variant="secondary" aria-label="Cancel" onClick={cancel} icon={X} style={{ padding: '9px 10px' }} />
                        </div>
                    ) : (
                        <button type="button" onClick={() => setEditing(true)}
                            style={{ display: 'flex', alignItems: 'center', gap: 5, marginTop: 6, fontSize: 11.5, color: 'var(--text-tertiary)', background: 'none', border: 'none', padding: 0, cursor: 'pointer', fontFamily: 'ui-monospace,monospace', maxWidth: '100%' }}>
                            <Pencil style={{ width: 11, height: 11, flexShrink: 0 }} />
                            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{repo.repo_url || 'Add git address…'}</span>
                        </button>
                    )}
                </div>
                <Button variant="danger" onClick={onRemove} disabled={busy} icon={Trash2}
                    title="Detach this repo from the project" aria-label={`Detach ${repo.name}`} style={{ padding: '7px 10px' }} />
            </div>

            <div style={{ borderTop: '1px solid var(--border-subtle)', marginTop: 12, paddingTop: 12 }}>
                <GitTokenField
                    hasToken={repo.has_token} valid={repo.token_valid} checkedAt={repo.token_checked_at}
                    label="Access token"
                    hint="Lets agents clone and push this repo."
                    onSave={async (t) => { await api.setProjectRepoToken(projectId, repo.name, t); await onReload(); }}
                    onCheck={async () => { await api.checkProjectRepoToken(projectId, repo.name); await onReload(); }} />
            </div>

            <Advanced label="Advanced">
                {repo.repo_path && (
                    <Field label="Folder on this machine">
                        <div style={{ fontSize: 12, color: 'var(--text-muted)', fontFamily: 'ui-monospace,monospace', wordBreak: 'break-all' }}>{repo.repo_path}</div>
                    </Field>
                )}
                <Field label="Keep branches up to date"
                    hint={`Main branch: ${repo.default_branch || 'main'}. Controls whether agents start from, and stay on top of, the newest code.`}>
                    <ChoiceList name={`fresh-${repo.name}`} disabled={busy}
                        value={repo.worktree_freshness || 'always_latest'}
                        onChange={(v) => onUpdate({ worktree_freshness: v })}
                        options={FRESHNESS} />
                </Field>
            </Advanced>
        </Card>
    );
}

function AddRepoForm({ onSubmit, busy, hasRepos }) {
    const [open, setOpen] = useState(false);
    const [name, setName] = useState('');
    const [repoUrl, setRepoUrl] = useState('');
    const [repoPath, setRepoPath] = useState('');
    const [defaultBranch, setDefaultBranch] = useState('main');
    const [isPrimary, setIsPrimary] = useState(false);
    const [info, setInfo] = useState(null);
    const edited = useRef({ name: false, branch: false });

    // Paste an address → fill in the name, and on GitHub the main branch too.
    // Anything the user typed themselves is never overwritten.
    useEffect(() => {
        const parsed = parseGitAddress(repoUrl);
        setInfo(null);
        if (!parsed) return undefined;
        if (!edited.current.name) setName(parsed.name);
        let cancelled = false;
        const t = setTimeout(async () => {
            const found = await fetchRepoInfo(parsed);
            if (cancelled || !found) return;
            setInfo(found);
            if (found.defaultBranch && !edited.current.branch) setDefaultBranch(found.defaultBranch);
        }, 400);
        return () => { cancelled = true; clearTimeout(t); };
    }, [repoUrl]);

    if (!open) {
        return <Button variant="secondary" icon={Plus} onClick={() => setOpen(true)}>Attach a repo</Button>;
    }

    const valid = name.trim() && (repoPath.trim() || repoUrl.trim());
    const submit = async (e) => {
        e.preventDefault();
        if (!valid) return;
        await onSubmit({
            name: name.trim(),
            repo_path: repoPath.trim(),
            repo_url: repoUrl.trim(),
            default_branch: defaultBranch.trim() || 'main',
            is_primary: isPrimary,
        });
        setName(''); setRepoPath(''); setRepoUrl('');
        setDefaultBranch('main'); setIsPrimary(false); setOpen(false);
        edited.current = { name: false, branch: false };
    };

    return (
        <form onSubmit={submit}>
            <Card>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 14 }}>Attach a repo</div>
                <Field label="Git address" htmlFor="ar-url" hint="Where the code lives, e.g. a GitHub link. Paste it and the name and main branch fill in by themselves. Agents clone it into their own workspace.">
                    <TextField id="ar-url" mono autoFocus value={repoUrl} onChange={(e) => setRepoUrl(e.target.value)} placeholder="https://github.com/org/repo.git" />
                    {info && (
                        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginTop: 8 }}>
                            {info.language && <span style={badge('var(--accent-primary)', 'var(--accent-subtle)')}>{info.language}</span>}
                            <span style={badge('var(--text-muted)', 'var(--surface-hover)')}>{info.isPrivate ? 'private' : 'public'}</span>
                            {info.description && <span style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>{info.description}</span>}
                        </div>
                    )}
                </Field>
                <Field label="Name" htmlFor="ar-name" hint="A short label, e.g. “backend” or “website”. Filled in from the address; change it if you like. Tasks use it to say which repo they’re about.">
                    <TextField id="ar-name" value={name} onChange={(e) => { edited.current.name = true; setName(e.target.value); }} placeholder="backend" />
                </Field>
                {hasRepos && (
                    <Toggle id="ar-primary" checked={isPrimary} onChange={setIsPrimary}
                        label="Make this the default repo"
                        hint="Tasks that don’t name a repo use the default one." />
                )}
                <Advanced label="Advanced">
                    <Field label="Folder on this machine" htmlFor="ar-path"
                        hint="Only if there is no git address: a folder the daemon can read and branch from.">
                        <TextField id="ar-path" mono value={repoPath} onChange={(e) => setRepoPath(e.target.value)} placeholder="/path/to/repo" />
                    </Field>
                    <Field label="Main branch" htmlFor="ar-branch" hint="The branch new work starts from. Filled in from GitHub when it can be.">
                        <TextField id="ar-branch" value={defaultBranch} onChange={(e) => { edited.current.branch = true; setDefaultBranch(e.target.value); }} placeholder="main" />
                    </Field>
                </Advanced>
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
                    <Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
                    <Button type="submit" onClick={submit} disabled={busy || !valid} icon={Plus}>
                        {busy ? 'Attaching…' : 'Attach repo'}
                    </Button>
                </div>
            </Card>
        </form>
    );
}


// ── Run environment (Advanced) ───────────────────────────────────────────────

// How a project provisions its per-run DB (any engine) lives behind Advanced.
function EnvAdvanced({ form, bind }) {
    const showCmds = form.env_isolation === 'per_run_db' || form.env_isolation === 'per_run_compose';
    return (
        <Advanced label="Advanced">
            <p style={{ fontSize: 11.5, color: 'var(--text-tertiary)', margin: '0 0 14px' }}>
                Technical mode: <code>{form.env_isolation === 'auto' ? 'auto (resolved at dispatch)' : form.env_isolation}</code>
            </p>
            {showCmds ? (
                <>
                    <Field label="Setup command" htmlFor="ps-env-setup"
                        hint="Runs before each run, in the worktree. Provisions the run’s environment (any DB engine or language) and prints KEY=VALUE connection vars on stdout — e.g. AGENTIRA_DB_URL=… — which are injected into the agent. $AGENTIRA_RUN_SCOPE and $AGENTIRA_DB_ADMIN_URL are available. Required for “Separate database for each run”.">
                        <TextArea id="ps-env-setup" rows={2} mono
                            placeholder={'createdb "$AGENTIRA_RUN_SCOPE" && echo "AGENTIRA_DB_URL=postgres://localhost/$AGENTIRA_RUN_SCOPE"'}
                            {...bind('env_setup_cmd')} />
                    </Field>
                    <Field label="Teardown command" htmlFor="ps-env-teardown"
                        hint="Runs when the run finishes, however it ends. Drops what setup created. Blank for compose uses “docker compose down -v”.">
                        <TextArea id="ps-env-teardown" rows={2} mono
                            placeholder={'dropdb --if-exists "$AGENTIRA_RUN_SCOPE"'}
                            {...bind('env_teardown_cmd')} />
                    </Field>
                    <Field label="Database admin URL (optional)" htmlFor="ps-env-admin"
                        hint="Passed to setup and teardown as $AGENTIRA_DB_ADMIN_URL — the admin connection they use to create and drop the per-run database. Stored as-is.">
                        <TextField id="ps-env-admin" mono placeholder="postgres://admin@localhost:5432/postgres"
                            {...bind('env_db_admin_url')} />
                    </Field>
                </>
            ) : (
                <p style={{ fontSize: 11.5, color: 'var(--text-tertiary)', margin: 0 }}>
                    Setup and teardown commands only apply to the “separate database” and “separate full stack” modes.
                </p>
            )}
        </Advanced>
    );
}


// ── Danger zone ──────────────────────────────────────────────────────────────

// AP-332: destructive project delete, in its own section so it is never
// confused with Save; the delete goes through ConfirmModal.
function DangerZone({ projectId, projectName }) {
    const navigate = useNavigate();
    const [confirming, setConfirming] = useState(false);
    const [deleting, setDeleting] = useState(false);
    const [error, setError] = useState('');

    const remove = async () => {
        setDeleting(true);
        setError('');
        try {
            await api.deleteProject(projectId);
            // Navigating to the studio root remounts the dashboard and changes
            // the active projectId, so the navbar + sidebar drop the project.
            navigate(ROUTES.STUDIO);
        } catch (err) {
            setError('Delete failed: ' + (err.message || err));
            setDeleting(false);
            setConfirming(false);
        }
    };

    return (
        <SettingsSection title="Danger zone" description="Actions here can’t be undone.">
            <Card tone="danger">
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: 600, color: '#f87171', marginBottom: 6 }}>
                    <AlertTriangle style={{ width: 14, height: 14 }} /> Delete this project
                </div>
                <p style={{ fontSize: 12.5, color: 'var(--text-muted)', margin: '0 0 14px' }}>
                    Deleting <strong style={{ color: 'var(--text-primary)' }}>{projectName || 'this project'}</strong> permanently
                    removes it and everything inside — all tasks, runs, chats, and attached files.
                </p>
                <Button variant="danger" icon={Trash2} onClick={() => setConfirming(true)} disabled={deleting}>
                    {deleting ? 'Deleting…' : 'Delete project'}
                </Button>
                {error && <div style={{ marginTop: 12 }}><Notice tone="error">{error}</Notice></div>}
            </Card>

            {confirming && (
                <ConfirmModal
                    isDanger
                    title={`Delete "${projectName || 'this project'}"?`}
                    message={
                        'This permanently deletes the project and everything in it — '
                        + 'all tasks, runs, chats, and attached files. This cannot be undone.'
                    }
                    confirmText={deleting ? 'Deleting…' : 'Delete permanently'}
                    cancelText="Cancel"
                    onConfirm={remove}
                    onCancel={() => setConfirming(false)}
                />
            )}
        </SettingsSection>
    );
}
