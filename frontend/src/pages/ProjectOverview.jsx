/**
 * Project Overview — the landing page for a project.
 *
 * Renders a one-screen snapshot: description, repos, member list, task
 * counts by status, recent activity tail, and quick links to the
 * board / backlog / roadmap. Pulls from existing /api/projects/{id}/...
 * endpoints; no new backend.
 */

import React, { useEffect, useState, useRef, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
    Folder, GitBranch, Users, Activity, ChevronDown,
    Paperclip, Upload, FileText, Trash2, Download,
    MessageSquare, Plus, ArrowRight, Pencil, ArrowUpRight,
} from 'lucide-react';
import { api } from '../api';
import { ROUTES } from '../routes';
import { ProjectActivityPanel } from '../components/ProjectActivityPanel';


function formatSize(bytes) {
    if (!bytes) return '0 B';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}


function timeAgo(iso) {
    if (!iso) return '';
    // Activity timestamps are naive UTC; append Z so they parse as UTC.
    const then = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + 'Z');
    const s = Math.floor((Date.now() - then.getTime()) / 1000);
    if (isNaN(s)) return '';
    if (s < 60) return 'just now';
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
    if (s < 604800) return `${Math.floor(s / 86400)}d ago`;
    return then.toLocaleDateString();
}


export function ProjectOverview() {
    const { projectId } = useParams();
    const [project, setProject] = useState(null);
    const [members, setMembers] = useState([]);
    const [repos, setRepos] = useState([]);
    const [board, setBoard] = useState(null);
    const [activity, setActivity] = useState([]);
    const [attachments, setAttachments] = useState([]);
    const [loading, setLoading] = useState(true);

    const reloadAttachments = useCallback(async () => {
        try {
            const list = await api.listProjectAttachments(projectId);
            setAttachments(list || []);
        } catch { /* keep prior */ }
    }, [projectId]);

    useEffect(() => {
        let alive = true;
        (async () => {
            try {
                const [p, m, r, b, a, att] = await Promise.all([
                    api.getProject(projectId).catch(() => null),
                    api.getProjectMembers(projectId).catch(() => []),
                    api.listProjectRepos(projectId).catch(() => []),
                    api.getBoard(projectId).catch(() => null),
                    api.getProjectActivity(projectId, 20).catch(() => []),
                    api.listProjectAttachments(projectId).catch(() => []),
                ]);
                if (!alive) return;
                setProject(p);
                setMembers(m || []);
                setRepos(r || []);
                setBoard(b);
                setActivity(a || []);
                setAttachments(att || []);
            } finally {
                if (alive) setLoading(false);
            }
        })();
        return () => { alive = false; };
    }, [projectId]);

    if (loading) {
        return <div className="p-8 text-text-tertiary">Loading…</div>;
    }
    if (!project) {
        return <div className="p-8 text-text-secondary">Project not found.</div>;
    }

    const statusCounts = countByStatus(board);

    return (
        <div className="flex-1 overflow-y-auto">
            {/* Live activity strip — the same "what's running" panel as the
                board, polling in-flight runs + the Conductor every 5s. */}
            <ProjectActivityPanel projectId={projectId} />

            <div className="max-w-5xl mx-auto p-6 space-y-6">
                {/* Recent activity — runs, comments, task changes (clickable) */}
                <ActivityCard items={activity} projectId={projectId} />

                {/* Status counts */}
                <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
                    <Stat label="Backlog" value={statusCounts.backlog} />
                    <Stat label="To do" value={statusCounts.todo} />
                    <Stat label="In progress" value={statusCounts.in_progress}
                        accent />
                    <Stat label="Review" value={statusCounts.review} />
                    <Stat label="Done" value={statusCounts.done} />
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <ReposCard repos={repos} projectId={projectId} />
                    <TeamCard members={members} />
                </div>

                <AttachmentsCard
                    projectId={projectId}
                    attachments={attachments}
                    onChange={reloadAttachments}
                />
            </div>
        </div>
    );
}


function Stat({ label, value, accent }) {
    return (
        <div className="card text-center">
            <div className={`text-2xl font-bold ${accent ? 'text-accent-primary' : 'text-text-primary'}`}>
                {value}
            </div>
            <div className="text-xs text-text-tertiary uppercase tracking-wider mt-1">
                {label}
            </div>
        </div>
    );
}


function ReposCard({ repos, projectId }) {
    return (
        <div className="card space-y-3">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-sm font-medium text-text-primary">
                    <Folder className="w-4 h-4" /> Repositories
                    <span className="text-text-tertiary text-xs">{repos.length}</span>
                </div>
                <Link to={ROUTES.STUDIO_PROJECT_SETTINGS(projectId) + '#repos'}
                    className="text-xs text-accent-primary hover:underline">
                    Manage
                </Link>
            </div>
            {repos.length === 0 ? (
                <div className="text-xs text-text-tertiary">
                    No repos attached. Add one in Settings → Repos.
                </div>
            ) : (
                <div className="space-y-1.5">
                    {repos.map((r) => (
                        <div key={r.id || r.name}
                            className="flex items-center gap-2 px-2 py-1.5 rounded bg-bg-hover">
                            <GitBranch className="w-3.5 h-3.5 text-text-tertiary" />
                            <span className="text-sm text-text-primary">{r.name}</span>
                            {r.is_primary && (
                                <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-accent-subtle text-accent-primary">
                                    primary
                                </span>
                            )}
                            <span className="text-xs text-text-tertiary font-mono truncate ml-auto">
                                {r.repo_path || r.repo_url}
                            </span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}


// UI-only role/responsibility profiles. The platform doesn't yet expose a
// per-member "what they do" field, so we infer a function from the member's
// name/role and show a short responsibility blurb. Placeholder copy — to be
// replaced once the backend exposes real role definitions.
const ROLE_PROFILES = [
    { match: /front.?end|^fe\b|web|ui/i,        function: 'Frontend',      blurb: 'Builds and refines the product UI — pages, components, and client-side behavior.' },
    { match: /back.?end|^be\b|api|server/i,     function: 'Backend',       blurb: 'Owns API endpoints, data models, and server-side business logic.' },
    { match: /implement|engineer|dev|coder/i,   function: 'Implementer',   blurb: 'Picks up scoped tasks and turns them into working, tested code.' },
    { match: /plan(ner)?|pm|product/i,          function: 'Planner',       blurb: 'Breaks goals into tasks, sets priorities, and shapes the backlog.' },
    { match: /review|qa|critic/i,               function: 'Reviewer',      blurb: 'Reviews changes for correctness and quality before they merge.' },
    { match: /test|qe/i,                        function: 'Test',          blurb: 'Writes and runs tests; verifies behavior and guards against regressions.' },
    { match: /admin|owner|lead/i,               function: 'Admin',         blurb: 'Manages the project, members, and overall workflow.' },
    { match: /bot|agent|conductor/i,            function: 'Automation',    blurb: 'Automated agent that runs scheduled or triggered work.' },
];

const FUNCTION_COLORS = {
    Frontend: '#00bcd4', Backend: '#7c4dff', Implementer: '#2ecc71',
    Planner: '#f1c40f', Reviewer: '#ff9800', Test: '#e91e63',
    Admin: '#e74c3c', Automation: '#9aa0a6', Contributor: '#9aa0a6',
};

function memberProfile(m) {
    const key = `${m.name || ''} ${m.display_name || ''} ${m.role || ''}`;
    const found = ROLE_PROFILES.find((p) => p.match.test(key));
    return found || {
        function: 'Contributor',
        blurb: 'Contributes to the project. Responsibilities to be defined.',
    };
}


function TeamMemberRow({ member }) {
    const [open, setOpen] = useState(false);
    const profile = memberProfile(member);
    const color = FUNCTION_COLORS[profile.function] || FUNCTION_COLORS.Contributor;
    const name = member.display_name || member.name || '?';
    return (
        <div className="rounded-md bg-bg-hover/60 overflow-hidden">
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className="w-full flex items-center gap-2 px-2 py-1.5 text-left hover:bg-bg-hover transition-colors"
            >
                <div className="w-7 h-7 rounded-full bg-accent-subtle text-accent-primary flex items-center justify-center text-xs font-bold flex-shrink-0">
                    {name[0]?.toUpperCase()}
                </div>
                <div className="min-w-0">
                    <div className="text-sm text-text-primary truncate">{name}</div>
                    <div className="text-[11px] text-text-tertiary truncate">@{member.name}</div>
                </div>
                <span
                    className="ml-auto text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded flex-shrink-0"
                    style={{ backgroundColor: color + '22', color }}
                >
                    {profile.function}
                </span>
                <ChevronDown
                    className={`w-4 h-4 text-text-tertiary flex-shrink-0 transition-transform ${open ? 'rotate-180' : ''}`}
                />
            </button>
            {open && (
                <div className="px-3 pb-2.5 pt-0.5 text-xs text-text-secondary leading-relaxed border-t border-border-subtle/60">
                    {profile.blurb}
                    {member.role && (
                        <div className="mt-1 text-text-tertiary">
                            Access role: <span className="text-text-secondary">{member.role}</span>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}


function TeamCard({ members }) {
    return (
        <div className="card space-y-3">
            <div className="flex items-center gap-2 text-sm font-medium text-text-primary">
                <Users className="w-4 h-4" /> Team &amp; roles
                <span className="text-text-tertiary text-xs">{members.length}</span>
            </div>
            {members.length === 0 ? (
                <div className="text-xs text-text-tertiary">No members yet.</div>
            ) : (
                <div className="space-y-1.5">
                    {members.map((m) => (
                        <TeamMemberRow key={m.id || m.name} member={m} />
                    ))}
                </div>
            )}
        </div>
    );
}


// Maps a raw activity `action` to an icon, accent color, and human label.
const ACTION_META = {
    commented:     { icon: MessageSquare, color: '#7c4dff', label: 'commented' },
    'task.create': { icon: Plus,          color: '#2ecc71', label: 'created task' },
    'task.move':   { icon: ArrowRight,    color: '#00bcd4', label: 'moved task' },
    'task.update': { icon: Pencil,        color: '#f1c40f', label: 'updated task' },
};

function actionMeta(action) {
    return ACTION_META[action] || { icon: Activity, color: '#9aa0a6', label: action || 'activity' };
}


// SPA-aware link: internal app paths route through react-router (no full
// reload); external URLs open in a new tab. Used for links embedded in
// activity details (e.g. run links like /forge/runs/<id> and PR URLs).
function SmartLink({ href, children, ...rest }) {
    const isInternal = typeof href === 'string' && href.startsWith('/');
    if (isInternal) {
        return (
            <Link to={href} className="text-accent-primary hover:underline" {...rest}>
                {children}
            </Link>
        );
    }
    return (
        <a href={href} target="_blank" rel="noopener noreferrer"
            className="text-accent-primary hover:underline" {...rest}>
            {children}
        </a>
    );
}

// Compact markdown for activity details — tight spacing, clickable links.
const FEED_MD_COMPONENTS = {
    a: ({ node, ...p }) => <SmartLink {...p} />,
    p: (p) => <p className="text-sm text-text-secondary leading-snug my-0.5" {...p} />,
    ul: (p) => <ul className="list-disc pl-5 my-1 text-sm text-text-secondary space-y-0.5" {...p} />,
    ol: (p) => <ol className="list-decimal pl-5 my-1 text-sm text-text-secondary space-y-0.5" {...p} />,
    li: (p) => <li className="text-sm text-text-secondary" {...p} />,
    strong: (p) => <strong className="text-text-primary font-semibold" {...p} />,
    em: (p) => <em className="italic" {...p} />,
    code: (p) => <code className="px-1 py-0.5 rounded bg-bg-panel text-xs font-mono text-text-primary" {...p} />,
    h1: (p) => <p className="text-sm font-semibold text-text-primary my-0.5" {...p} />,
    h2: (p) => <p className="text-sm font-semibold text-text-primary my-0.5" {...p} />,
    h3: (p) => <p className="text-sm font-semibold text-text-primary my-0.5" {...p} />,
};


function ActivityRow({ entry, projectId }) {
    const meta = actionMeta(entry.action);
    const Icon = meta.icon;
    const actor = entry.actor || 'system';
    return (
        <div className="flex gap-3 px-2 py-2.5 rounded-md hover:bg-bg-hover/50 transition-colors">
            <div className="w-7 h-7 rounded-full bg-accent-subtle flex items-center justify-center text-xs font-bold text-accent-primary border border-accent-primary/20 flex-shrink-0">
                {actor[0]?.toUpperCase() || 'S'}
            </div>
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap text-xs">
                    <span className="font-semibold text-text-primary">{actor}</span>
                    <span className="inline-flex items-center gap-1 text-text-secondary">
                        <Icon className="w-3 h-3" style={{ color: meta.color }} />
                        {meta.label}
                    </span>
                    <span className="text-text-tertiary">· {timeAgo(entry.created_at)}</span>
                    {entry.task_id && (
                        <Link
                            to={ROUTES.STUDIO_TASK(entry.task_id)}
                            className="ml-auto inline-flex items-center gap-0.5 text-text-tertiary hover:text-accent-primary transition-colors"
                            title="Open task"
                        >
                            #{String(entry.task_id).slice(0, 8)}
                            <ArrowUpRight className="w-3 h-3" />
                        </Link>
                    )}
                </div>
                {entry.detail && (
                    <div className="mt-1 max-h-44 overflow-y-auto">
                        <ReactMarkdown remarkPlugins={[remarkGfm]} components={FEED_MD_COMPONENTS}>
                            {String(entry.detail)}
                        </ReactMarkdown>
                    </div>
                )}
            </div>
        </div>
    );
}


function ActivityCard({ items, projectId }) {
    return (
        <div className="card space-y-1">
            <div className="flex items-center gap-2 text-sm font-medium text-text-primary mb-1">
                <Activity className="w-4 h-4 text-accent-primary" /> Recent activity
            </div>
            {items.length === 0 ? (
                <div className="text-xs text-text-tertiary py-2">Nothing yet.</div>
            ) : (
                <div className="divide-y divide-border-subtle/60">
                    {items.map((a, i) => (
                        <ActivityRow key={a.id || i} entry={a} projectId={projectId} />
                    ))}
                </div>
            )}
        </div>
    );
}


// AP-152: project-level attachments — drag-and-drop, list, download, delete.
// Lives on the dashboard (NOT Settings) because briefs/designs are
// project content the team works with daily, not a one-time config.
function AttachmentsCard({ projectId, attachments, onChange }) {
    const fileInputRef = useRef(null);
    const [dragActive, setDragActive] = useState(false);
    const [uploading, setUploading] = useState(false);

    const uploadFiles = async (fileList) => {
        const files = Array.from(fileList || []);
        if (!files.length) return;
        setUploading(true);
        try {
            for (const f of files) {
                await api.uploadProjectAttachment(projectId, f);
            }
            await onChange();
        } catch (err) {
            alert('Upload failed: ' + (err.message || err));
        } finally {
            setUploading(false);
        }
    };

    const handleDelete = async (att) => {
        if (!window.confirm(`Delete ${att.filename}?`)) return;
        try {
            await api.deleteAttachment(att.id);
            await onChange();
        } catch (err) {
            alert('Delete failed: ' + (err.message || err));
        }
    };

    return (
        <div className="card space-y-3">
            <div className="flex items-center gap-2 text-sm font-medium text-text-primary">
                <Paperclip className="w-4 h-4" /> Attachments
                <span className="text-text-tertiary text-xs">{attachments.length}</span>
            </div>
            <div
                className="rounded-lg p-4 text-center cursor-pointer transition-all"
                style={{
                    border: `2px dashed ${dragActive ? 'var(--accent-primary)' : 'var(--border-subtle)'}`,
                    backgroundColor: dragActive ? 'var(--accent-subtle)' : 'var(--bg-app)',
                }}
                onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
                onDragLeave={() => setDragActive(false)}
                onDrop={(e) => { e.preventDefault(); setDragActive(false); uploadFiles(e.dataTransfer.files); }}
                onClick={() => fileInputRef.current?.click()}
            >
                <Upload className="w-5 h-5 mx-auto mb-1.5" style={{ color: dragActive ? 'var(--accent-primary)' : 'var(--text-tertiary)' }} />
                <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                    {uploading
                        ? 'Uploading…'
                        : <>Drop files here or <span style={{ color: 'var(--accent-primary)', fontWeight: 600 }}>click to browse</span></>}
                </p>
                <p className="text-[10px] mt-0.5" style={{ color: 'var(--text-tertiary)' }}>
                    Briefs, designs, brand guides — agents can read text inline; binary fetched on demand.
                </p>
                <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    className="hidden"
                    onChange={(e) => { uploadFiles(e.target.files); e.target.value = ''; }}
                />
            </div>
            {attachments.length > 0 && (
                <div className="space-y-1">
                    {attachments.map((a) => (
                        <div key={a.id}
                            className="flex items-center gap-2 px-3 py-1.5 rounded-md text-xs"
                            style={{ backgroundColor: 'var(--bg-panel)', border: '1px solid var(--border-subtle)' }}
                        >
                            <FileText className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--accent-primary)' }} />
                            <span className="flex-1 truncate" style={{ color: 'var(--text-primary)' }}>{a.filename}</span>
                            <span className="flex-shrink-0" style={{ color: 'var(--text-tertiary)' }}>{formatSize(a.size_bytes)}</span>
                            <a
                                href={api.getAttachmentDownloadUrl(a.id)}
                                target="_blank"
                                rel="noreferrer"
                                className="p-0.5 rounded-lg hover:bg-bg-hover"
                                style={{ color: 'var(--text-tertiary)' }}
                                title="Download"
                            >
                                <Download className="w-3 h-3" />
                            </a>
                            <button
                                type="button"
                                onClick={() => handleDelete(a)}
                                className="p-0.5 rounded-lg hover:bg-red-500/10 transition-colors"
                                style={{ color: 'var(--text-tertiary)' }}
                                title="Delete"
                            >
                                <Trash2 className="w-3 h-3" />
                            </button>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}


function countByStatus(board) {
    const out = { backlog: 0, todo: 0, in_progress: 0, review: 0, done: 0 };
    if (!board || !board.columns) return out;
    for (const status of Object.keys(out)) {
        out[status] = (board.columns[status] || []).length;
    }
    return out;
}
