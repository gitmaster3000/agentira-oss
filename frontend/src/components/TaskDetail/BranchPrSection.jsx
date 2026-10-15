import React, { useState, useEffect } from 'react';
import {
    GitBranch,
    GitCommit,
    GitPullRequest,
    ExternalLink,
    Copy,
    Check,
    Pencil,
} from 'lucide-react';
import { api } from '../../api';
import { CollapsibleSection } from './CollapsibleSection';

function formatBranchDisplay(val) {
    if (!val) return '';
    const treeMatch = val.match(/\/tree\/(.+)$/);
    if (treeMatch) return treeMatch[1];
    if (val.startsWith('http')) return val.replace(/^https?:\/\/(www\.)?/, '');
    return val;
}

function formatPrDisplay(val) {
    if (!val) return '';
    const prMatch = val.match(/github\.com\/[^/]+\/([^/]+)\/pull\/(\d+)/);
    if (prMatch) return `${prMatch[1]}#${prMatch[2]}`;
    if (val.startsWith('http')) return val.replace(/^https?:\/\/(www\.)?/, '');
    return val;
}

// Branch & PR card. The inline-edit state (which field is open, its draft and
// the copy tick) lives here, so typing a branch name re-renders only this card.
export function BranchPrSection({ task, taskId, commits, open, onToggle, onSaved }) {
    const [branchValue, setBranchValue] = useState(task.branch || '');
    const [prUrlValue, setPrUrlValue] = useState(task.pr_url || '');
    const [editingBranch, setEditingBranch] = useState(false);
    const [editingPrUrl, setEditingPrUrl] = useState(false);
    const [copiedField, setCopiedField] = useState(null);

    useEffect(() => { setBranchValue(task.branch || ''); }, [task.branch]);
    useEffect(() => { setPrUrlValue(task.pr_url || ''); }, [task.pr_url]);

    const copyToClipboard = (text, field) => {
        navigator.clipboard.writeText(text);
        setCopiedField(field);
        setTimeout(() => setCopiedField(null), 800);
    };

    const saveBranch = async (val) => {
        setEditingBranch(false);
        if (val !== (task.branch || '')) {
            await api.updateTask(taskId, { branch: val });
            onSaved();
        }
    };

    const savePrUrl = async (val) => {
        setEditingPrUrl(false);
        if (val !== (task.pr_url || '')) {
            await api.updateTask(taskId, { pr_url: val });
            onSaved();
        }
    };

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
                {editingBranch ? (
                    <input
                        className="w-full px-2 py-1.5 text-sm bg-bg-app border border-border-subtle rounded font-mono text-text-primary focus:outline-none focus:border-accent-primary"
                        value={branchValue}
                        onChange={e => setBranchValue(e.target.value)}
                        onBlur={() => saveBranch(branchValue)}
                        onKeyDown={e => e.key === 'Enter' && saveBranch(branchValue)}
                        autoFocus
                    />
                ) : (
                    <div className="flex items-center gap-1.5">
                        {branchValue ? (
                            <>
                                {branchValue.startsWith('http') ? (
                                    <a href={branchValue} target="_blank" rel="noopener noreferrer" className="text-sm font-mono text-accent-primary hover:underline truncate">
                                        {formatBranchDisplay(branchValue)}
                                    </a>
                                ) : (
                                    <span className="text-sm font-mono text-text-primary truncate">{branchValue}</span>
                                )}
                                <button onClick={() => setEditingBranch(true)} className="p-0.5 text-text-tertiary hover:text-text-secondary transition-colors flex-shrink-0" title="Edit">
                                    <Pencil className="w-3 h-3" />
                                </button>
                                <button onClick={() => copyToClipboard(branchValue, 'branch')} className="p-0.5 text-text-tertiary hover:text-accent-primary transition-colors flex-shrink-0" title="Copy">
                                    {copiedField === 'branch' ? <Check className="w-3 h-3 text-green-500" /> : <Copy className="w-3 h-3" />}
                                </button>
                            </>
                        ) : (
                            <span className="text-xs text-text-tertiary italic cursor-pointer hover:text-text-secondary" onClick={() => setEditingBranch(true)}>No branch set</span>
                        )}
                    </div>
                )}
            </div>

            <div className="mb-4 min-w-0">
                <div className="text-[10px] font-bold uppercase text-text-secondary mb-1">Pull Request</div>
                {editingPrUrl ? (
                    <input
                        className="w-full px-2 py-1.5 text-sm bg-bg-app border border-border-subtle rounded text-text-primary focus:outline-none focus:border-accent-primary"
                        value={prUrlValue}
                        onChange={e => setPrUrlValue(e.target.value)}
                        onBlur={() => savePrUrl(prUrlValue)}
                        onKeyDown={e => e.key === 'Enter' && savePrUrl(prUrlValue)}
                        placeholder="https://github.com/..."
                        autoFocus
                    />
                ) : (
                    <div className="flex items-center gap-1.5">
                        {prUrlValue ? (
                            <>
                                <a href={prUrlValue} target="_blank" rel="noopener noreferrer" className="text-sm text-accent-primary hover:underline truncate">
                                    {formatPrDisplay(prUrlValue)}
                                </a>
                                <button onClick={() => setEditingPrUrl(true)} className="p-0.5 text-text-tertiary hover:text-text-secondary transition-colors flex-shrink-0" title="Edit">
                                    <Pencil className="w-3 h-3" />
                                </button>
                                <button onClick={() => copyToClipboard(prUrlValue, 'pr')} className="p-0.5 text-text-tertiary hover:text-accent-primary transition-colors flex-shrink-0" title="Copy">
                                    {copiedField === 'pr' ? <Check className="w-3 h-3 text-green-500" /> : <Copy className="w-3 h-3" />}
                                </button>
                            </>
                        ) : (
                            <span className="text-xs text-text-tertiary italic cursor-pointer hover:text-text-secondary" onClick={() => setEditingPrUrl(true)}>No PR linked</span>
                        )}
                    </div>
                )}
            </div>
            </div>

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
