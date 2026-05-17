import React, { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import {
    Activity, ChevronDown, ChevronRight, Loader, CheckCircle,
    Ban, XCircle, HelpCircle, Bot, ClipboardList,
} from 'lucide-react';
import { api } from '../api';

const POLL_MS = 5000;

/**
 * ProjectActivityPanel — live "what's running" summary for a project.
 *
 * Polls GET /forge/projects/{id}/activity every 5s: a 24h run digest plus
 * the Conductor's view (its agents for this project, their load, next
 * task). Collapsible — collapsed shows the headline counts, expanded
 * shows active runs + the Conductor's agents.
 */
export function ProjectActivityPanel({ projectId }) {
    const [data, setData] = useState(null);
    const [open, setOpen] = useState(true);
    const [stale, setStale] = useState(false);
    const timer = useRef(null);

    useEffect(() => {
        if (!projectId) return;
        let alive = true;
        const tick = async () => {
            try {
                const d = await api.forge.getProjectActivity(projectId);
                if (alive) { setData(d); setStale(false); }
            } catch {
                if (alive) setStale(true);
            }
        };
        tick();
        timer.current = setInterval(tick, POLL_MS);
        return () => { alive = false; clearInterval(timer.current); };
    }, [projectId]);

    if (!data) return null;

    const counts = data.digest?.counts || {};
    const stats = data.digest?.stats || {};
    const inFlight = data.digest?.in_flight || [];
    const agents = data.conductor?.agents || [];

    return (
        <div className="shrink-0 border-b border-border-subtle bg-bg-app">
            {/* Headline row — always visible */}
            <button
                onClick={() => setOpen((v) => !v)}
                className="w-full flex items-center gap-3 px-4 py-2 text-left hover:bg-bg-hover/40"
            >
                {open ? <ChevronDown className="w-4 h-4 text-text-tertiary" />
                      : <ChevronRight className="w-4 h-4 text-text-tertiary" />}
                <Activity className="w-4 h-4 text-accent-primary" />
                <span className="text-sm font-medium text-text-primary">Activity</span>
                <span className="flex items-center gap-3 text-xs text-text-secondary">
                    <Stat icon={Loader} color="#f1c40f" n={counts.in_flight}
                          label="running" spin={(counts.in_flight || 0) > 0} />
                    <Stat icon={CheckCircle} color="#2ecc71" n={counts.done} label="done" />
                    <Stat icon={Ban} color="#e91e63" n={counts.blocked} label="blocked" />
                    <Stat icon={HelpCircle} color="#ff9800" n={counts.needs_input} label="needs input" />
                    <Stat icon={XCircle} color="#e74c3c" n={counts.failed} label="failed" />
                </span>
                <span className="ml-auto text-xs text-text-tertiary">
                    {stale && <span className="text-yellow-500 mr-2">reconnecting…</span>}
                    last 24h{stats.cost_usd ? ` · $${stats.cost_usd}` : ''}
                </span>
            </button>

            {open && (
                <div className="px-4 pb-3 grid grid-cols-1 md:grid-cols-2 gap-4">
                    {/* Active runs */}
                    <div>
                        <div className="text-[11px] uppercase tracking-wider text-text-tertiary mb-1.5">
                            Active runs ({inFlight.length})
                        </div>
                        {inFlight.length === 0 ? (
                            <div className="text-xs text-text-tertiary italic">Nothing running right now.</div>
                        ) : (
                            <div className="space-y-1 max-h-40 overflow-y-auto">
                                {inFlight.map((r) => (
                                    <Link
                                        key={r.id}
                                        to={`/forge/runs/${r.id}?from=runs`}
                                        className="flex items-center gap-2 px-2 py-1 rounded bg-bg-hover hover:bg-bg-app text-xs"
                                    >
                                        <Loader className="w-3 h-3 text-yellow-500 animate-spin flex-shrink-0" />
                                        <ClipboardList className="w-3 h-3 text-text-tertiary flex-shrink-0" />
                                        <span className="truncate text-text-secondary">
                                            {r.task_key || r.task_title || `run ${String(r.id).slice(0, 8)}`}
                                        </span>
                                        {r.status && (
                                            <span className="ml-auto text-text-tertiary">{r.status}</span>
                                        )}
                                    </Link>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* Conductor view */}
                    <div>
                        <div className="text-[11px] uppercase tracking-wider text-text-tertiary mb-1.5">
                            Conductor
                            {data.conductor?.tick_seconds
                                ? ` · ticks every ${data.conductor.tick_seconds}s`
                                : ''}
                        </div>
                        {agents.length === 0 ? (
                            <div className="text-xs text-text-tertiary italic">
                                No conductor-enabled agents on this project.
                            </div>
                        ) : (
                            <div className="space-y-1 max-h-40 overflow-y-auto">
                                {agents.map((a) => (
                                    <div
                                        key={a.agent}
                                        className="flex items-center gap-2 px-2 py-1 rounded bg-bg-hover text-xs"
                                    >
                                        <Bot className="w-3 h-3 text-text-tertiary flex-shrink-0" />
                                        <span className="text-text-primary truncate">{a.name}</span>
                                        <span className="text-text-tertiary">
                                            {a.in_flight}/{a.capacity}
                                        </span>
                                        <span className="ml-auto truncate text-text-tertiary max-w-[55%]">
                                            {a.next_task
                                                ? `next: ${a.next_task.title}`
                                                : 'idle — nothing queued'}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}

function Stat({ icon: Icon, color, n, label, spin }) {
    return (
        <span className="inline-flex items-center gap-1" title={label}>
            <Icon className={`w-3.5 h-3.5 ${spin ? 'animate-spin' : ''}`} style={{ color }} />
            <span className="tabular-nums">{n || 0}</span>
        </span>
    );
}
