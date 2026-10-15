import React from 'react';
import {
    GitBranch,
    GitCommit,
    GitPullRequest,
    ExternalLink,
    Copy,
    Check,
    Pencil,
} from 'lucide-react';
import { CollapsibleSection } from './CollapsibleSection';
import { useGitFields, formatBranchDisplay, formatPrDisplay } from './useGitFields';

// Branch & PR card. The inline-edit state lives in useGitFields, inside this
// card, so typing a branch name re-renders only the card.
export function BranchPrSection({ task, commits, open, onToggle, onSaved }) {
    const { branch, pr, copiedField, copyToClipboard, error } = useGitFields(task, onSaved);

    return (
        <CollapsibleSection
            title="Branch & PR"
            icon={GitBranch}
            open={open}
            onToggle={onToggle}
            separated
        >
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-6">
            <div className="mb-4 min-w-0">
                <div className="text-[10px] font-bold uppercase text-text-secondary mb-1">Branch</div>
                {branch.editing ? (
                    <input
                        className="w-full px-2 py-1.5 text-sm bg-bg-app border border-border-subtle rounded font-mono text-text-primary focus:outline-none focus:border-accent-primary"
                        {...branch.inputProps()}
                    />
                ) : (
                    <div className="flex items-center gap-1.5">
                        {branch.value ? (
                            <>
                                {branch.value.startsWith('http') ? (
                                    <a href={branch.value} target="_blank" rel="noopener noreferrer" className="text-sm font-mono text-accent-primary hover:underline truncate">
                                        {formatBranchDisplay(branch.value)}
                                    </a>
                                ) : (
                                    <span className="text-sm font-mono text-text-primary truncate">{branch.value}</span>
                                )}
                                <button onClick={() => branch.setEditing(true)} className="p-0.5 text-text-tertiary hover:text-text-secondary transition-colors flex-shrink-0" title="Edit">
                                    <Pencil className="w-3 h-3" />
                                </button>
                                <button onClick={() => copyToClipboard(branch.value, 'branch')} className="p-0.5 text-text-tertiary hover:text-accent-primary transition-colors flex-shrink-0" title="Copy">
                                    {copiedField === 'branch' ? <Check className="w-3 h-3 text-green-500" /> : <Copy className="w-3 h-3" />}
                                </button>
                            </>
                        ) : (
                            <span className="text-xs text-text-tertiary italic cursor-pointer hover:text-text-secondary" onClick={() => branch.setEditing(true)}>No branch set</span>
                        )}
                    </div>
                )}
            </div>

            <div className="mb-4 min-w-0">
                <div className="text-[10px] font-bold uppercase text-text-secondary mb-1">Pull Request</div>
                {pr.editing ? (
                    <input
                        className="w-full px-2 py-1.5 text-sm bg-bg-app border border-border-subtle rounded text-text-primary focus:outline-none focus:border-accent-primary"
                        {...pr.inputProps()}
                        placeholder="https://github.com/..."
                    />
                ) : (
                    <div className="flex items-center gap-1.5">
                        {pr.value ? (
                            <>
                                <a href={pr.value} target="_blank" rel="noopener noreferrer" className="text-sm text-accent-primary hover:underline truncate">
                                    {formatPrDisplay(pr.value)}
                                </a>
                                <button onClick={() => pr.setEditing(true)} className="p-0.5 text-text-tertiary hover:text-text-secondary transition-colors flex-shrink-0" title="Edit">
                                    <Pencil className="w-3 h-3" />
                                </button>
                                <button onClick={() => copyToClipboard(pr.value, 'pr')} className="p-0.5 text-text-tertiary hover:text-accent-primary transition-colors flex-shrink-0" title="Copy">
                                    {copiedField === 'pr' ? <Check className="w-3 h-3 text-green-500" /> : <Copy className="w-3 h-3" />}
                                </button>
                            </>
                        ) : (
                            <span className="text-xs text-text-tertiary italic cursor-pointer hover:text-text-secondary" onClick={() => pr.setEditing(true)}>No PR linked</span>
                        )}
                    </div>
                )}
            </div>
            </div>
            {error && <p role="alert" className="text-xs text-red-400 mb-3">{error}</p>}

            {commits.length > 0 && (
                <>
                    <div className="text-[10px] font-bold uppercase text-text-secondary mb-1.5">Commits & PRs ({commits.length})</div>
                    <div className="space-y-1.5">
                        {commits.map((c) => (
                            <div key={c.id} className="flex items-center gap-2 px-2.5 py-1.5 rounded bg-bg-app border border-border-subtle/30 text-sm">
                                {c.kind === 'pr'
                                    ? <GitPullRequest className="w-3.5 h-3.5 text-purple-400 flex-shrink-0" />
                                    : <GitCommit className="w-3.5 h-3.5 text-text-secondary flex-shrink-0" />
                                }
                                <div className="flex-1 min-w-0">
                                    <div className="text-text-primary truncate text-xs">
                                        {c.kind === 'pr' ? `#${c.pr_number} ` : `${c.sha.slice(0, 7)} `}{c.message}
                                    </div>
                                    <div className="text-[10px] text-text-secondary">
                                        {c.author}{c.branch ? ` on ${c.branch}` : ''}
                                        {c.kind === 'pr' && c.pr_state && (
                                            <span className={`ml-1.5 px-1 py-0.5 rounded text-[9px] font-medium ${
                                                c.pr_state === 'merged' ? 'bg-purple-500/20 text-purple-400' :
                                                c.pr_state === 'open' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                                            }`}>{c.pr_state}</span>
                                        )}
                                    </div>
                                </div>
                                {c.url && (
                                    <a href={c.url} target="_blank" rel="noopener noreferrer" className="text-text-tertiary hover:text-accent-primary transition-colors flex-shrink-0">
                                        <ExternalLink className="w-3 h-3" />
                                    </a>
                                )}
                            </div>
                        ))}
                    </div>
                </>
            )}
        </CollapsibleSection>
    );
}
