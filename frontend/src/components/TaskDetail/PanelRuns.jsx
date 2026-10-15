import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Play, Cpu } from 'lucide-react';
import { api } from '../../api';
import { ROUTES } from '../../routes';
import { SectionLabel, relTime } from './PanelFeed';

export const LIVE_RUN_STATUSES = ['pending', 'running', 'interrupting'];

// "Agent working now" banner + recent agent runs + Run-with-agent (AP-301).
export function PanelRuns({ task, members, taskRuns, onRunsChanged }) {
    const navigate = useNavigate();
    const [scheduling, setScheduling] = useState(false);
    const liveRun = taskRuns.find(r => LIVE_RUN_STATUSES.includes(r.status));
    const workRuns = taskRuns.filter(r => r.is_work);

    const handleRunWithAgent = async () => {
        setScheduling(true);
        try {
            const agents = await api.forge.listAgents();
            const agent = (Array.isArray(agents) ? agents : []).find(a => a.runtime_id && a.name === task.assignee);
            if (!agent) throw new Error('The assigned agent has no runtime. Set one up first.');
            const result = await api.forge.prepareTaskRun(task.id, agent.id);
            await onRunsChanged();
            const runId = result.id || result.run_id;
            if (runId) navigate(ROUTES.FORGE_RUN(runId));
        } catch (err) {
            console.error('Prepare run failed:', err);
            alert('Failed to prepare run: ' + (err.message || err));
        } finally {
            setScheduling(false);
        }
    };

    return (
        <>
            {liveRun && (
                <div
                    onClick={() => navigate(ROUTES.FORGE_RUN(liveRun.id))}
                    className="agent-active-glow flex items-center gap-2 cursor-pointer"
                    style={{ padding: 10, borderRadius: 10, background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', marginBottom: 16 }}
                >
                    <span style={{ width: 24, height: 24, borderRadius: 7, background: 'rgba(0,188,212,.14)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#00bcd4" strokeWidth="2"><rect x="3" y="11" width="18" height="10" rx="2"></rect><circle cx="12" cy="5" r="2"></circle><path d="M12 7v4"></path></svg>
                    </span>
                    <div className="flex-1 min-w-0">
                        <div style={{ fontSize: 12, fontWeight: 600 }} className="text-text-primary">Agent working now</div>
                        <div style={{ fontSize: 10.5 }} className="text-text-tertiary">Open to watch the live run</div>
                    </div>
                    <span className="flex items-center" style={{ gap: 5, fontSize: 10, fontWeight: 700, color: 'var(--pulse-blue)' }}>
                        <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--pulse-blue)' }} />LIVE
                    </span>
                </div>
            )}

            <div className="flex items-center justify-between" style={{ marginBottom: 10 }}>
                <SectionLabel inline>Agent runs</SectionLabel>
                {members.some(p => p.account_type === 'agentira_agent' && p.name === task.assignee) && <button
                    disabled={scheduling}
                    onClick={handleRunWithAgent}
                    className="inline-flex items-center transition-colors"
                    style={{ gap: 5, fontSize: 11, fontWeight: 600, padding: '4px 9px', borderRadius: 7, background: 'var(--accent-subtle, rgba(124,77,255,.14))', color: 'var(--accent-primary, #7c4dff)' }}
                >
                    <Play className="w-3 h-3" /> Run with agent
                </button>}
            </div>
            {workRuns.length > 0 ? (
                <div style={{ marginBottom: 16 }}>
                    {workRuns.slice(0, 5).map(r => (
                        <button
                            key={r.id}
                            onClick={() => navigate(ROUTES.FORGE_RUN(r.id))}
                            className="w-full flex items-center transition-colors hover:bg-bg-card"
                            style={{ gap: 8, padding: '6px 8px', borderRadius: 8, textAlign: 'left' }}
                        >
                            <Cpu className="w-3 h-3 flex-shrink-0 text-text-tertiary" />
                            <span style={{ fontSize: 12 }} className="text-text-primary truncate">{r.agent_name || r.agent_id}</span>
                            <span style={{ fontSize: 10.5 }} className="text-text-tertiary ml-auto">{r.status}</span>
                            <span style={{ fontSize: 10 }} className="text-text-tertiary">{relTime(r.created_at)}</span>
                        </button>
                    ))}
                </div>
            ) : (
                <p style={{ fontSize: 11.5, marginBottom: 16 }} className="text-text-tertiary">No agent runs yet. Launch one to get started.</p>
            )}
        </>
    );
}
