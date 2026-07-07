import React from 'react';
import { UserPlus, Rocket, Bell, CheckCircle2, XCircle } from 'lucide-react';
import { processSteps, gateConditions } from '../../lib/workflowRules';

const STEP_ICON = { assign: UserPlus, dispatch: Rocket, notify: Bell };

function ProcessZone({ columnName, flow }) {
    const steps = processSteps(columnName, flow);
    return (
        <div className="rounded-lg border border-border-subtle bg-bg-app p-4">
            <div className="text-label-md uppercase tracking-wider text-tertiary mb-3">Process — on enter</div>
            {steps.length === 0 ? (
                <div className="text-body-sm text-tertiary">No on-enter actions configured for this column.</div>
            ) : (
                <ul className="flex flex-col gap-2">
                    {steps.map((step, i) => {
                        const Icon = STEP_ICON[step.kind] || Bell;
                        return (
                            <li key={i} className="flex items-center gap-2.5 rounded-md px-3 py-2" style={{ background: 'var(--accent-subtle)' }}>
                                <Icon className="w-3.5 h-3.5 text-accent-primary shrink-0" />
                                <span className="text-body-sm text-primary">{step.label}</span>
                            </li>
                        );
                    })}
                </ul>
            )}
        </div>
    );
}

function GateZone({ columnName, flow }) {
    const { to, conditions } = gateConditions(columnName, flow);
    return (
        <div className="rounded-lg border border-border-subtle bg-bg-app p-4">
            <div className="flex items-center justify-between mb-3">
                <div className="text-label-md uppercase tracking-wider text-tertiary">Gate{to ? ` — exit to ${to}` : ''}</div>
                {to ? (
                    <div className="flex items-center gap-3 text-label-sm">
                        <span className="flex items-center gap-1" style={{ color: 'var(--success)' }}><CheckCircle2 className="w-3.5 h-3.5" /> Allow</span>
                        <span className="flex items-center gap-1" style={{ color: 'var(--danger)' }}><XCircle className="w-3.5 h-3.5" /> Block</span>
                    </div>
                ) : null}
            </div>
            {!to ? (
                <div className="text-body-sm text-tertiary">Terminal column — no outbound gate.</div>
            ) : conditions.length === 0 ? (
                <div className="text-body-sm text-tertiary">No conditions configured — the transition always allows.</div>
            ) : (
                <ul className="flex flex-col gap-2">
                    {conditions.map((c) => (
                        <li key={c.id} className="flex items-start gap-2.5 rounded-md px-3 py-2 border border-border-subtle">
                            <span
                                className="text-[9.5px] font-bold uppercase tracking-wider rounded-full px-2 py-0.5 shrink-0"
                                style={c.source === 'evidence'
                                    ? { background: 'var(--tint-success)', color: 'var(--success)' }
                                    : { background: 'var(--tint-warning)', color: 'var(--warning)' }}
                                title={c.source === 'evidence' ? 'verified — fetched by the platform' : 'asserted — a task field, not independently verified'}
                            >
                                {c.source === 'evidence' ? 'verified' : 'asserted'}
                            </span>
                            <div className="min-w-0">
                                <div className="text-body-sm text-primary font-mono">{c.expr}</div>
                                <div className="text-label-sm text-tertiary">{c.reason}</div>
                            </div>
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}

/** Selected-column canvas: PROCESS zone (on-enter steps) + GATE zone (exit conditions). */
export function ColumnCanvas({ columnName, flow }) {
    return (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <ProcessZone columnName={columnName} flow={flow} />
            <GateZone columnName={columnName} flow={flow} />
        </div>
    );
}
