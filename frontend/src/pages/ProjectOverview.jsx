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
import {
    Folder, GitBranch, Users, ListChecks, Activity, ChevronRight,
    Settings as SettingsIcon, LayoutGrid, ListTodo, TrendingUp,
    Paperclip, Upload, FileText, Trash2, Download,
} from 'lucide-react';
import { api } from '../api';
import { ROUTES } from '../routes';


function formatSize(bytes) {
    if (!bytes) return '0 B';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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
                    api.getProjectActivity(projectId, 8).catch(() => []),
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
            <div className="max-w-5xl mx-auto p-6 space-y-6">
                {/* Quick links */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <QuickLink to={ROUTES.STUDIO_PROJECT_BOARD(projectId)}
                        icon={LayoutGrid} label="Board" />
                    <QuickLink to={ROUTES.STUDIO_PROJECT_BACKLOG(projectId)}
                        icon={ListTodo} label="Backlog" />
                    <QuickLink to={ROUTES.STUDIO_PROJECT_ROADMAP(projectId)}
                        icon={TrendingUp} label="Roadmap" />
                    <QuickLink to={ROUTES.STUDIO_PROJECT_SETTINGS(projectId)}
                        icon={SettingsIcon} label="Settings" />
                </div>

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
                    <MembersCard members={members} />
                </div>

                <AttachmentsCard
                    projectId={projectId}
                    attachments={attachments}
                    onChange={reloadAttachments}
                />

                <ActivityCard items={activity} />
            </div>
        </div>
    );
}


function QuickLink({ to, icon: Icon, label }) {
    return (
        <Link to={to}
            className="card flex items-center gap-3 hover:bg-bg-hover transition-colors">
            <div className="w-8 h-8 rounded-lg bg-accent-subtle flex items-center justify-center">
                <Icon className="w-4 h-4 text-accent-primary" />
            </div>
            <div className="text-sm font-medium text-text-primary">{label}</div>
            <ChevronRight className="w-4 h-4 text-text-tertiary ml-auto" />
        </Link>
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


function MembersCard({ members }) {
    return (
        <div className="card space-y-3">
            <div className="flex items-center gap-2 text-sm font-medium text-text-primary">
                <Users className="w-4 h-4" /> Members
                <span className="text-text-tertiary text-xs">{members.length}</span>
            </div>
            {members.length === 0 ? (
                <div className="text-xs text-text-tertiary">No members yet.</div>
            ) : (
                <div className="flex flex-wrap gap-2">
                    {members.map((m) => (
                        <div key={m.id || m.name}
                            className="flex items-center gap-2 px-2 py-1 rounded bg-bg-hover">
                            <div className="w-6 h-6 rounded-full bg-accent-subtle text-accent-primary flex items-center justify-center text-xs font-bold">
                                {(m.display_name || m.name || '?')[0]?.toUpperCase()}
                            </div>
                            <span className="text-sm text-text-primary">
                                {m.display_name || m.name}
                            </span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}


function ActivityCard({ items }) {
    return (
        <div className="card space-y-2">
            <div className="flex items-center gap-2 text-sm font-medium text-text-primary">
                <Activity className="w-4 h-4" /> Recent activity
            </div>
            {items.length === 0 ? (
                <div className="text-xs text-text-tertiary">Nothing yet.</div>
            ) : (
                <div className="space-y-1.5">
                    {items.map((a, i) => (
                        <div key={a.id || i} className="text-xs text-text-secondary flex gap-2">
                            <span className="text-text-tertiary whitespace-nowrap">
                                {a.actor || 'system'}
                            </span>
                            <span className="text-text-tertiary">·</span>
                            <span>{a.action}</span>
                            {a.detail && (
                                <span className="text-text-tertiary truncate">
                                    — {a.detail.slice(0, 80)}
                                </span>
                            )}
                        </div>
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
