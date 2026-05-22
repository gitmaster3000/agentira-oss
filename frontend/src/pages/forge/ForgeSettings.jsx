/**
 * AP-130: Forge Settings — Run defaults panel.
 *
 * Read-only audit of the hardcoded run knobs (max_turns, auto-retry,
 * stale-run threshold, stop-grace, etc.) so the user can SEE the
 * configuration surface without thinking it's missing. Promoting any
 * of these to per-project overrides is a future ticket.
 *
 * Project settings live on the project page itself (contextually
 * correct). Agents have their own config editor in AgentDetail.
 */

import React from 'react';
import { Activity, Info } from 'lucide-react';


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
    return (
        <div className="flex-1 p-6 space-y-6 max-w-3xl mx-auto w-full">
            <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-accent-subtle flex items-center justify-center">
                    <Activity className="w-5 h-5 text-accent-primary" />
                </div>
                <div>
                    <h1 className="text-2xl font-bold text-text-primary">Run defaults</h1>
                    <p className="text-sm text-text-secondary">
                        The values the runtime, daemon, and reconciler use today.
                    </p>
                </div>
            </div>

            <div className="card bg-blue-500/5 border border-blue-500/20 flex items-start gap-3">
                <Info className="w-5 h-5 text-blue-400 flex-shrink-0 mt-0.5" />
                <div className="text-sm text-text-secondary">
                    Not editable from the UI yet — promoting any of these to per-project overrides is a future ticket.
                    Project settings live on the project page; agent settings live on the agent page.
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
