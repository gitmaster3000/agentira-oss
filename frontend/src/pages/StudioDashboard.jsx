import React, { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Folder, ArrowRight, Plus, Clock } from 'lucide-react';
import { api } from '../api';

const LAST_PROJECT_KEY = 'agentira:studio:lastProjectId';

/**
 * Studio landing page. Replaces the old bone-dry "Welcome" stub.
 *
 * Goals:
 *  - One useful page (not empty) when the user lands on /studio
 *  - "Resume where you left off" → last-visited project (localStorage)
 *  - Project picker right there, no need to fish in the sidebar
 *  - Click any card → goes to that project's board
 */
export function StudioDashboard() {
    const navigate = useNavigate();
    const [projects, setProjects] = useState(null);

    useEffect(() => {
        api.getProjects()
            .then(d => setProjects(Array.isArray(d) ? d : []))
            .catch(() => setProjects([]));
    }, []);

    const lastProjectId = (() => {
        try { return localStorage.getItem(LAST_PROJECT_KEY) || ''; } catch { return ''; }
    })();
    const lastProject = projects?.find(p => p.id === lastProjectId);

    if (projects === null) {
        return (
            <div className="flex-1 flex items-center justify-center text-text-tertiary">
                Loading…
            </div>
        );
    }

    return (
        <div className="flex-1 overflow-auto">
            <div className="max-w-5xl mx-auto p-8 space-y-8">
                {/* Header */}
                <div>
                    <h1 className="text-2xl font-bold text-text-primary mb-1">Studio</h1>
                    <p className="text-sm text-text-tertiary">
                        Your projects and tasks. Pick a project to open its board, or start a new one.
                    </p>
                </div>

                {/* Resume */}
                {lastProject && (
                    <div className="card flex items-center justify-between hover:bg-bg-hover transition-colors cursor-pointer"
                         onClick={() => navigate(`/studio/board/${lastProject.id}`)}>
                        <div className="flex items-center gap-3 min-w-0">
                            <div className="w-10 h-10 rounded-lg bg-accent-subtle flex items-center justify-center">
                                <Clock className="w-5 h-5 text-accent-primary" />
                            </div>
                            <div className="min-w-0">
                                <div className="text-xs text-text-tertiary uppercase tracking-wider">Resume where you left off</div>
                                <div className="text-base font-semibold text-text-primary truncate">{lastProject.name}</div>
                            </div>
                        </div>
                        <ArrowRight className="w-5 h-5 text-text-tertiary" />
                    </div>
                )}

                {/* Projects */}
                <div>
                    <div className="flex items-center justify-between mb-4">
                        <h2 className="text-sm font-semibold text-text-primary uppercase tracking-wider">Projects</h2>
                        <span className="text-xs text-text-tertiary">{projects.length}</span>
                    </div>
                    {projects.length === 0 ? (
                        <div className="card text-center py-12 text-text-tertiary">
                            <Folder className="w-10 h-10 mx-auto mb-3 opacity-40" />
                            <p>No projects yet.</p>
                            <p className="text-xs mt-2">Use <span className="px-1.5 py-0.5 rounded bg-bg-hover">+ New</span> in the sidebar to create one.</p>
                        </div>
                    ) : (
                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                            {projects.map(p => (
                                <Link
                                    key={p.id}
                                    to={`/studio/board/${p.id}`}
                                    onClick={() => { try { localStorage.setItem(LAST_PROJECT_KEY, p.id); } catch {} }}
                                    className="card hover:bg-bg-hover transition-colors block"
                                >
                                    <div className="flex items-center justify-between mb-2">
                                        <div className="flex items-center gap-2 min-w-0">
                                            <Folder className="w-4 h-4 text-text-tertiary shrink-0" />
                                            <span className="font-semibold text-text-primary truncate">{p.name}</span>
                                        </div>
                                        {p.key_prefix && (
                                            <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-bg-hover text-text-tertiary shrink-0">
                                                {p.key_prefix}
                                            </span>
                                        )}
                                    </div>
                                    {p.description && (
                                        <p className="text-xs text-text-tertiary line-clamp-2 mb-2">{p.description}</p>
                                    )}
                                    <div className="flex items-center gap-3 text-[11px] text-text-tertiary mt-2 pt-2 border-t border-border-subtle">
                                        {typeof p.task_count === 'number' && (
                                            <span>{p.task_count} task{p.task_count === 1 ? '' : 's'}</span>
                                        )}
                                        {Array.isArray(p.members) && p.members.length > 0 && (
                                            <span>{p.members.length} member{p.members.length === 1 ? '' : 's'}</span>
                                        )}
                                        {p.repo_path && (
                                            <span className="font-mono truncate ml-auto max-w-[50%]" title={p.repo_path}>
                                                {p.repo_path}
                                            </span>
                                        )}
                                    </div>
                                </Link>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
