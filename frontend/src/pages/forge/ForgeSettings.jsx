/**
 * AP-130: Forge Settings hub.
 *
 * Surfaces the configuration knobs that ALREADY exist on Profile and
 * Project but were "barebones" / scattered before. Three sections:
 *
 *  1. Run defaults — read-only audit panel. Shows the hardcoded values
 *     so the user can SEE the configuration surface without thinking
 *     it's missing. New configurable knobs are out of scope for this
 *     PR (good defaults beat configurable bad ones).
 *  2. Agents — list of agents linking into the existing AgentDetail
 *     config editor.
 *  3. Projects — inline editor for repo_path / repo_url / conventions
 *     (the knobs the daemon dispatch path reads).
 */

import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
    Bot, Folder, Settings as SettingsIcon, ChevronRight,
    Save, Info, FileText, Cpu, Activity,
} from 'lucide-react';
import { api } from '../../api';

// AP-130: read-only mirror of the hardcoded run knobs. Updating these
// values when the code changes is the trade we make for not exposing
// configuration we don't actually want users editing yet.
const RUN_DEFAULTS = [
    {
        label: 'Max turns per run',
        value: '300',
        source: 'agentira-cli/runtimes/claude.py',
        why: 'Cap on agentic turns before a run is forcefully ended. 300 leaves ample headroom for typical coding tasks while still bounding a runaway loop.',
    },
    {
        label: 'Auto-retry on subprocess crash',
        value: 'up to 2 retries within 20 min',
        source: 'backend/forge/services.py (_AUTO_RETRY_MAX, _AUTO_RETRY_WINDOW_MIN)',
        why: 'Transient subprocess crashes (API blips, claude-code hiccups) re-dispatch on the same session. The cap stops a retry storm on a genuinely broken task.',
    },
    {
        label: 'Stale-run threshold',
        value: '120 s',
        source: 'backend/forge/reconciler.py (STALE_RUN_THRESHOLD_S)',
        why: 'How long a RUNNING run can go without a daemon heartbeat before the reconciler flips it to FAILED. Heartbeat cadence is well under a minute; 120s gives slack for network blips.',
    },
    {
        label: 'Stop grace (SIGTERM → SIGKILL)',
        value: '5 s',
        source: 'agentira-cli/daemon/core.py (_STOP_GRACE_S)',
        why: 'Time the daemon waits for claude to exit cleanly after SIGTERM before escalating to SIGKILL on the whole process group. Long enough for in-flight MCP calls to drain, short enough that Stop feels responsive.',
    },
    {
        label: 'Transient-state escalation',
        value: '30 s',
        source: 'backend/forge/reconciler.py (STUCK_TRANSIENT_THRESHOLD_S)',
        why: 'How long a run can sit in PAUSING / CANCELLING / RESUMING before the reconciler assumes the daemon dropped the frame and forces the terminal state.',
    },
    {
        label: 'Per-event content cap (run events MCP)',
        value: '4 KB',
        source: 'backend/forge/services.py (_EVENT_CONTENT_CAP)',
        why: 'Maximum bytes of any single event content surfaced through get_run_events. Larger tool_results are suffixed with "…[truncated]" so an investigator agent doesn\'t blow its context on one giant output.',
    },
];


export function ForgeSettings() {
    const [tab, setTab] = useState('defaults');

    return (
        <div className="flex-1 p-6 space-y-6 max-w-5xl mx-auto w-full">
            <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-accent-subtle flex items-center justify-center">
                    <SettingsIcon className="w-5 h-5 text-accent-primary" />
                </div>
                <div>
                    <h1 className="text-2xl font-bold text-text-primary">Forge Settings</h1>
                    <p className="text-sm text-text-secondary">
                        Configure agents, projects, and inspect the run defaults.
                    </p>
                </div>
            </div>

            <div className="flex gap-2 border-b border-border-subtle">
                <TabButton active={tab === 'defaults'} onClick={() => setTab('defaults')}
                    icon={Activity} label="Run defaults" />
                <TabButton active={tab === 'agents'} onClick={() => setTab('agents')}
                    icon={Bot} label="Agents" />
                <TabButton active={tab === 'projects'} onClick={() => setTab('projects')}
                    icon={Folder} label="Projects" />
            </div>

            {tab === 'defaults' && <RunDefaultsPanel />}
            {tab === 'agents' && <AgentsPanel />}
            {tab === 'projects' && <ProjectsPanel />}
        </div>
    );
}


function TabButton({ active, onClick, icon: Icon, label }) {
    return (
        <button
            onClick={onClick}
            className={`flex items-center gap-2 px-4 py-2 -mb-px border-b-2 transition-colors text-sm font-medium ${
                active
                    ? 'border-accent-primary text-accent-primary'
                    : 'border-transparent text-text-secondary hover:text-text-primary'
            }`}
        >
            <Icon className="w-4 h-4" />
            {label}
        </button>
    );
}


function RunDefaultsPanel() {
    return (
        <div className="space-y-4">
            <div className="card bg-blue-500/5 border border-blue-500/20 flex items-start gap-3">
                <Info className="w-5 h-5 text-blue-400 flex-shrink-0 mt-0.5" />
                <div className="text-sm text-text-secondary">
                    These are the hardcoded defaults the runtime, daemon, and reconciler use. They aren't editable from
                    the UI yet — promoting any of them to per-project overrides is a future ticket. This panel
                    exists so you can audit the surface without thinking it's missing.
                </div>
            </div>
            <div className="grid gap-3">
                {RUN_DEFAULTS.map((d, i) => (
                    <div key={i} className="card">
                        <div className="flex items-baseline justify-between gap-3 mb-1">
                            <div className="text-sm font-medium text-text-primary">{d.label}</div>
                            <div className="text-base font-mono text-accent-primary whitespace-nowrap">{d.value}</div>
                        </div>
                        <p className="text-xs text-text-secondary">{d.why}</p>
                        <div className="text-[10px] text-text-tertiary font-mono mt-2 truncate">{d.source}</div>
                    </div>
                ))}
            </div>
        </div>
    );
}


function AgentsPanel() {
    const [agents, setAgents] = useState(null);
    useEffect(() => {
        api.forge.listAgents().then(setAgents).catch(() => setAgents([]));
    }, []);
    if (agents === null) {
        return <div className="text-text-tertiary text-sm">Loading agents…</div>;
    }
    if (agents.length === 0) {
        return (
            <div className="card text-text-tertiary text-sm">
                No agents yet. Create one from the Agents page.
            </div>
        );
    }
    return (
        <div className="grid gap-2">
            {agents.map((a) => (
                <Link
                    key={a.id}
                    to={`/forge/agents/${a.id}`}
                    className="card flex items-center gap-3 hover:bg-bg-hover transition-colors"
                >
                    <Bot className="w-5 h-5 text-text-secondary flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium text-text-primary truncate">{a.name}</div>
                        <div className="text-xs text-text-tertiary truncate">
                            {a.model || '—'} · max concurrent: {a.max_concurrent_runs ?? 1}
                            {a.is_system && ' · system'}
                        </div>
                    </div>
                    <ChevronRight className="w-4 h-4 text-text-tertiary flex-shrink-0" />
                </Link>
            ))}
        </div>
    );
}


function ProjectsPanel() {
    const [projects, setProjects] = useState(null);
    useEffect(() => {
        api.getProjects().then(setProjects).catch(() => setProjects([]));
    }, []);
    if (projects === null) {
        return <div className="text-text-tertiary text-sm">Loading projects…</div>;
    }
    if (projects.length === 0) {
        return (
            <div className="card text-text-tertiary text-sm">
                No projects yet. Create one from the Studio dashboard.
            </div>
        );
    }
    return (
        <div className="grid gap-3">
            {projects.map((p) => <ProjectCard key={p.id} project={p} />)}
        </div>
    );
}


function ProjectCard({ project }) {
    const [repoPath, setRepoPath] = useState(project.repo_path || '');
    const [repoUrl, setRepoUrl] = useState(project.repo_url || '');
    const [conventions, setConventions] = useState(project.conventions_md || '');
    const [saving, setSaving] = useState(false);
    const [msg, setMsg] = useState('');
    const dirty = repoPath !== (project.repo_path || '')
        || repoUrl !== (project.repo_url || '')
        || conventions !== (project.conventions_md || '');

    const save = async () => {
        setSaving(true);
        setMsg('');
        try {
            await api.updateProject(project.id, {
                repo_path: repoPath || null,
                repo_url: repoUrl || null,
                conventions_md: conventions || null,
            });
            setMsg('Saved');
            setTimeout(() => setMsg(''), 2000);
        } catch (err) {
            setMsg('Error: ' + (err.message || err));
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="card space-y-3">
            <div className="flex items-center gap-2">
                <Folder className="w-4 h-4 text-text-secondary" />
                <div className="text-sm font-medium text-text-primary">{project.name}</div>
                {project.template_name && (
                    <span className="text-[10px] text-text-tertiary uppercase tracking-wider">
                        template: {project.template_name}
                    </span>
                )}
            </div>

            <Field label="Repo path" hint="Absolute filesystem path the daemon worktrees off (same-machine).">
                <input
                    className="input"
                    placeholder="/path/to/repo"
                    value={repoPath}
                    onChange={(e) => setRepoPath(e.target.value)}
                />
            </Field>

            <Field label="Repo URL" hint="Optional — daemon clones from here when repo_path isn't accessible.">
                <input
                    className="input"
                    placeholder="https://github.com/org/repo.git"
                    value={repoUrl}
                    onChange={(e) => setRepoUrl(e.target.value)}
                />
            </Field>

            <Field label="Conventions (markdown)" hint="Materialized as .agentira/CONVENTIONS.md in the agent workdir.">
                <textarea
                    className="input font-mono text-xs"
                    rows="4"
                    placeholder="# Conventions&#10;Use ruff. Commit on a feature branch."
                    value={conventions}
                    onChange={(e) => setConventions(e.target.value)}
                />
            </Field>

            <div className="flex items-center gap-3">
                <button
                    className="btn btn-primary"
                    onClick={save}
                    disabled={!dirty || saving}
                >
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


function Field({ label, hint, children }) {
    return (
        <div>
            <label className="block text-xs text-text-tertiary mb-1">{label}</label>
            {children}
            {hint && <p className="text-xs text-text-tertiary mt-1">{hint}</p>}
        </div>
    );
}
