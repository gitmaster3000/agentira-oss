/**
 * Project Overview — the landing page for a project.
 *
 * Renders a one-screen snapshot: description, repos, member list, task
 * counts by status, recent activity tail, and quick links to the
 * board / backlog / roadmap. Pulls from existing /api/projects/{id}/...
 * endpoints; no new backend.
 */

import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
    Folder, GitBranch, Users, ListChecks, Activity, ChevronRight,
    Settings as SettingsIcon, LayoutGrid, ListTodo, TrendingUp,
} from 'lucide-react';
import { api } from '../api';
import { ROUTES } from '../routes';


export function ProjectOverview() {
    const { projectId } = useParams();
    const [project, setProject] = useState(null);
    const [members, setMembers] = useState([]);
    const [repos, setRepos] = useState([]);
    const [board, setBoard] = useState(null);
    const [activity, setActivity] = useState([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let alive = true;
        (async () => {
            try {
                const [p, m, r, b, a] = await Promise.all([
                    api.getProject(projectId).catch(() => null),
                    api.getProjectMembers(projectId).catch(() => []),
                    api.listProjectRepos(projectId).catch(() => []),
                    api.getBoard(projectId).catch(() => null),
                    api.getProjectActivity(projectId, 8).catch(() => []),
                ]);
                if (!alive) return;
                setProject(p);
                setMembers(m || []);
                setRepos(r || []);
                setBoard(b);
                setActivity(a || []);
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


function countByStatus(board) {
    const out = { backlog: 0, todo: 0, in_progress: 0, review: 0, done: 0 };
    if (!board || !board.columns) return out;
    for (const status of Object.keys(out)) {
        out[status] = (board.columns[status] || []).length;
    }
    return out;
}
