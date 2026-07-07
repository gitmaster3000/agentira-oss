import React from 'react';
import { processSteps, gateConditions } from '../../lib/workflowRules';

// Right-hand detail panel for the selected column: its PROCESS (what runs when
// a task arrives), its GATE (the real checks that must pass before a task can
// leave — sourced from the backend gate engine), and the PROMPT template the
// agent picking up this column receives. Vertical layout for the side rail.

function SectionLabel({ dot, children }) {
    return (
        <div style={{ display: 'flex', alignItems: 'center', gap: '7px', marginBottom: '11px' }}>
            <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: dot }} />
            <span style={{ fontSize: '10px', letterSpacing: '.1em', textTransform: 'uppercase', color: '#aeb6c0', fontWeight: 600 }}>{children}</span>
        </div>
    );
}

const StepIcon = ({ kind }) => {
    if (kind === 'assign') return <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: '18px', height: '18px', borderRadius: '50%', background: '#c9b8ff', fontSize: '9px', fontWeight: 700, color: '#0e1117', flexShrink: 0 }}>R</span>;
    if (kind === 'dispatch') return <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#00bcd4" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}><path d="M6 4l14 8-14 8V4z" /></svg>;
    return <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#00bcd4" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0" /></svg>;
};

function ProcessSection({ columnName, flow }) {
    const steps = processSteps(columnName, flow);
    return (
        <div style={{ background: 'rgba(0,188,212,.05)', border: '1px solid rgba(0,188,212,.22)', borderRadius: '12px', padding: '15px 15px' }}>
            <SectionLabel dot="#00bcd4">Process · on enter</SectionLabel>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '7px' }}>
                {steps.length === 0 ? (
                    <div style={{ fontSize: '12px', color: '#768390' }}>No process — tasks pass straight through.</div>
                ) : steps.map((step, i) => (
                    <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: '9px', background: '#14161b', border: '1px solid #30363d', borderLeft: '2px solid #00bcd4', borderRadius: '9px', padding: '9px 12px' }}>
                        <StepIcon kind={step.kind} />
                        <span style={{ fontSize: '12px', color: '#e8ebf0' }}>{step.label}</span>
                    </span>
                ))}
            </div>
        </div>
    );
}

function GateSection({ columnName, flow, columnsUi }) {
    const { to, conditions } = gateConditions(columnName, flow, columnsUi);
    return (
        <div style={{ background: 'rgba(128,203,196,.05)', border: '1px solid rgba(128,203,196,.26)', borderRadius: '12px', padding: '15px 15px' }}>
            <SectionLabel dot="#80cbc4">Gate · on exit</SectionLabel>
            {!to ? (
                <div style={{ fontSize: '12px', color: '#768390' }}>Terminal column — nothing leaves here.</div>
            ) : (
                <>
                    <div style={{ display: 'inline-flex', alignItems: 'center', gap: '7px', fontFamily: 'ui-monospace,SFMono-Regular,Menlo,monospace', fontSize: '11px', color: '#c8cdd4', background: '#0a0c10', border: '1px solid #30363d', borderRadius: '6px', padding: '5px 9px', marginBottom: '12px' }}>{columnName} <span style={{ color: '#768390' }}>→</span> {to}</div>
                    <div style={{ fontSize: '9px', letterSpacing: '.1em', textTransform: 'uppercase', color: '#768390', fontWeight: 600, marginBottom: '9px' }}>
                        {conditions.length === 0 ? 'No conditions · always allows' : 'Conditions · all must pass'}
                    </div>
                    {conditions.length === 0 ? (
                        <div style={{ background: '#14161b', border: '1px solid #30363d', borderRadius: '9px', padding: '10px 12px', fontFamily: 'ui-monospace,SFMono-Regular,Menlo,monospace', fontSize: '11px', color: '#768390' }}>return True</div>
                    ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '7px' }}>
                            {conditions.map((c) => (
                                <div key={c.id} style={{ background: '#14161b', border: '1px solid #30363d', borderLeft: '2px solid #80cbc4', borderRadius: '9px', padding: '9px 12px' }}>
                                    <div style={{ fontFamily: 'ui-monospace,SFMono-Regular,Menlo,monospace', fontSize: '11px', color: '#c8cdd4' }}>{c.expr}</div>
                                    <div style={{ fontSize: '10.5px', color: '#768390', marginTop: '3px' }}>{c.reason}</div>
                                </div>
                            ))}
                        </div>
                    )}
                    <div style={{ display: 'flex', gap: '8px', marginTop: '12px' }}>
                        <div style={{ flex: 1, background: 'rgba(46,204,113,.10)', border: '1px solid rgba(46,204,113,.45)', borderRadius: '9px', padding: '8px 10px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#2ecc71' }} /><span style={{ fontSize: '11.5px', fontWeight: 600, color: '#2ecc71' }}>Allow</span></div>
                            <div style={{ fontFamily: 'ui-monospace,SFMono-Regular,Menlo,monospace', fontSize: '9.5px', color: '#768390', marginTop: '3px' }}>→ {to}</div>
                        </div>
                        <div style={{ flex: 1, background: '#14161b', border: '1px solid #30363d', borderRadius: '9px', padding: '8px 10px', opacity: 0.6 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#f85149' }} /><span style={{ fontSize: '11.5px', fontWeight: 600, color: '#f85149' }}>Block</span></div>
                            <div style={{ fontFamily: 'ui-monospace,SFMono-Regular,Menlo,monospace', fontSize: '9.5px', color: '#768390', marginTop: '3px' }}>stays in {columnName}</div>
                        </div>
                    </div>
                </>
            )}
        </div>
    );
}

function PromptSection({ columnName, columnsUi }) {
    const detail = columnsUi?.[columnName];
    const role = detail?.prompt_role;
    const prompt = (detail?.prompt || '').trim();
    return (
        <div style={{ background: 'rgba(201,184,255,.05)', border: '1px solid rgba(201,184,255,.26)', borderRadius: '12px', padding: '15px 15px' }}>
            <SectionLabel dot="#c9b8ff">Prompt · handed to the agent</SectionLabel>
            {!prompt ? (
                <div style={{ fontSize: '12px', color: '#768390' }}>No prompt template — this column dispatches no role.</div>
            ) : (
                <>
                    {role && (
                        <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '10px', fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: '#c9b8ff', background: 'rgba(201,184,255,.12)', border: '1px solid rgba(201,184,255,.3)', borderRadius: '5px', padding: '3px 8px', marginBottom: '11px' }}>role: {role}</div>
                    )}
                    <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontFamily: 'ui-monospace,SFMono-Regular,Menlo,monospace', fontSize: '11px', lineHeight: 1.6, color: '#c8cdd4', background: '#0a0c10', border: '1px solid #30363d', borderRadius: '9px', padding: '12px 13px', maxHeight: '260px', overflowY: 'auto' }}>{prompt}</pre>
                </>
            )}
        </div>
    );
}

/** Detail rail for the selected column: process, gate (real checks), prompt. */
export function ColumnPanel({ columnName, flow, columnsUi }) {
    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', padding: '22px 20px' }}>
            <div style={{ fontSize: '15px', fontWeight: 700, color: '#f0f3f6' }}>{columnName}</div>
            <ProcessSection columnName={columnName} flow={flow} />
            <GateSection columnName={columnName} flow={flow} columnsUi={columnsUi} />
            <PromptSection columnName={columnName} columnsUi={columnsUi} />
        </div>
    );
}
