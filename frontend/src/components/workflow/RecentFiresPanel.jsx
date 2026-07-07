import React from 'react';
import { History } from 'lucide-react';

/** Recent transition attempts for the selected column. No transition_events /
 * gate_evaluations API exists yet — that lands in Phase 0 (AP-404) — so this
 * always renders the empty state until the backend ships one. */
export function RecentFiresPanel({ fires }) {
    return (
        <div className="rounded-lg border border-border-subtle bg-bg-app p-4">
            <div className="flex items-center gap-2 mb-3">
                <History className="w-3.5 h-3.5 text-tertiary" />
                <span className="text-label-md uppercase tracking-wider text-tertiary">Recent fires</span>
            </div>
            {!fires || fires.length === 0 ? (
                <div className="text-body-sm text-tertiary">
                    Evidence logging (transition_events + gate_evaluations) lands in Phase 0 — see AP-404.
                    Once it ships, every transition attempt on this column will show up here with its outcome and reason.
                </div>
            ) : (
                <ul className="flex flex-col gap-2">
                    {fires.map((f, i) => (
                        <li key={f.id || i} className="flex items-center justify-between text-body-sm">
                            <span className="text-primary">{f.task_key} — {f.from} → {f.to}</span>
                            <span style={{ color: f.outcome === 'allow' ? 'var(--success)' : 'var(--danger)' }}>{f.outcome}</span>
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}
