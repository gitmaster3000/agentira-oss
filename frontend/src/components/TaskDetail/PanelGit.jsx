import React, { useState } from 'react';
import {
    GitCommit, GitPullRequest, GitBranch, Copy, Check, Pencil, ExternalLink,
} from 'lucide-react';
import { SectionLabel } from './PanelFeed';
import { useGitFields, formatBranchDisplay, formatPrDisplay } from './useGitFields';

// Side-panel Branch & PR body. In edit mode the two fields are drafts that
// report to `draft` (a parent ref) and reseed from it if this section remounts,
// so typing never re-renders the panel and collapsing can't desync Save.
export function PanelGit({ task, commits, isEditing, draft, onSaved }) {
    const { branch, pr, copiedField, copyToClipboard, error } = useGitFields(task, onSaved);
    const [editBranch, setEditBranch] = useState(draft.current.branch ?? task.branch ?? '');
    const [editPr, setEditPr] = useState(draft.current.pr_url ?? task.pr_url ?? '');

    // Branch & PR are a per-repo 1:1 mapping. Surface which repo they belong to
    // so multi-repo tasks read correctly. `repo_name`/`repos` come from the API
    // (repos[0] is the task's first declared repo; falls back to primary repo).
    const taskRepos = task.repos || [];
    const repoLabel = task.repo_name || taskRepos[0] || '';

    return (
        <>
            {repoLabel && (
                <div className="flex items-center" style={{ gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
                    <span className="inline-flex items-center" style={{ gap: 5, fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 5, textTransform: 'uppercase', letterSpacing: '.04em', background: 'rgba(128,203,196,.12)', color: 'var(--brand-teal)' }}>
                        <GitBranch className="w-3 h-3" /> {repoLabel}
                    </span>
                    {taskRepos.length > 1 && <span style={{ fontSize: 10.5 }} className="text-text-tertiary">Branch &amp; PR apply to this repo</span>}
                </div>
            )}

            <SectionLabel>Branch</SectionLabel>
            <div style={{ marginBottom: 16 }}>
                {isEditing ? (
                    <input
                        aria-label="Branch"
                        className="w-full bg-bg-app border border-border-subtle rounded-lg font-mono text-text-primary focus:outline-none focus:border-accent-primary"
                        style={{ fontSize: 12, padding: '9px 11px' }}
                        value={editBranch}
                        onChange={e => { setEditBranch(e.target.value); draft.current.branch = e.target.value; }}
                        placeholder="feature/my-branch"
                    />
                ) : branch.editing ? (
                    <input
                        className="w-full bg-bg-card border border-border-subtle rounded-lg font-mono text-text-primary focus:outline-none focus:border-accent-primary"
                        style={{ fontSize: 12, padding: '9px 11px' }}
                        {...branch.inputProps()}
                    />
                ) : branch.value ? (
                    <div className="flex items-center" style={{ gap: 8, padding: '9px 11px', borderRadius: 9, background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', fontSize: 12 }}>
                        <GitBranch className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--brand-teal)' }} />
                        <span className="flex-1 font-mono truncate" style={{ color: 'var(--text-tertiary)' }}>{formatBranchDisplay(branch.value)}</span>
                        <button onClick={() => branch.setEditing(true)} className="text-text-tertiary hover:text-text-secondary"><Pencil className="w-3 h-3" /></button>
                        <button onClick={() => copyToClipboard(branch.value, 'branch')} className="text-text-tertiary hover:text-accent-primary">{copiedField === 'branch' ? <Check className="w-3 h-3 text-green-500" /> : <Copy className="w-3 h-3" />}</button>
                    </div>
                ) : (
                    <button onClick={() => branch.setEditing(true)} className="text-text-tertiary italic hover:text-text-secondary" style={{ fontSize: 12 }}>No branch set</button>
                )}
            </div>

            <SectionLabel>Pull Request</SectionLabel>
            <div style={{ marginBottom: 16 }}>
                {isEditing ? (
                    <input
                        aria-label="Pull Request"
                        className="w-full bg-bg-app border border-border-subtle rounded-lg text-text-primary focus:outline-none focus:border-accent-primary"
                        style={{ fontSize: 12, padding: '9px 11px' }}
                        value={editPr}
                        onChange={e => { setEditPr(e.target.value); draft.current.pr_url = e.target.value; }}
                        placeholder="https://github.com/…"
                    />
                ) : pr.editing ? (
                    <input
                        className="w-full bg-bg-card border border-border-subtle rounded-lg text-text-primary focus:outline-none focus:border-accent-primary"
                        style={{ fontSize: 12, padding: '9px 11px' }}
                        {...pr.inputProps()}
                        placeholder="https://github.com/…"
                    />
                ) : pr.value ? (
                    <a href={pr.value} target="_blank" rel="noopener noreferrer" className="flex items-center hover:border-border-strong transition-colors" style={{ gap: 8, padding: '9px 11px', borderRadius: 9, background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', fontSize: 12.5 }}>
                        <GitPullRequest className="w-3.5 h-3.5 flex-shrink-0" style={{ color: '#a78bfa' }} />
                        <span className="flex-1 font-mono truncate" style={{ color: 'var(--brand-teal)' }}>{formatPrDisplay(pr.value)}</span>
                        <ExternalLink className="w-3 h-3 text-text-tertiary" />
                    </a>
                ) : (
                    <button onClick={() => pr.setEditing(true)} className="text-text-tertiary italic hover:text-text-secondary" style={{ fontSize: 12 }}>No PR linked</button>
                )}
            </div>
            {error && <p role="alert" className="text-xs text-red-400" style={{ marginBottom: 12 }}>{error}</p>}

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
        </>
    );
}
