import React from 'react';
import { processSteps, gateConditions } from '../../lib/workflowRules';

// Visual canvas for the Workflow Engine — a verbatim port of the design's
// "Workflow Engine.dc.html" canvas (dotted grid → board zone → process zone →
// gate zone). Inline styles + SVG paths copied from the design so the chrome is
// pixel-identical; all content is real data from getBoard + getProjectWorkflow.

const DOT_RING = ['#768390', '#58a6ff', '#ff9800', '#38bdf8', '#2ecc71'];

const Gear = ({ s = 11 }) => (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="#00bcd4" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>
);

const Arrow = ({ s = 20, stroke = '#484f58' }) => (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 12h14M13 6l6 6-6 6" /></svg>
);

const DownArrow = () => (
    <div style={{ display: 'flex', justifyContent: 'center', padding: '11px 0' }}>
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#3a434f" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5v14M6 13l6 6 6-6" /></svg>
    </div>
);

// small lock badge that sits on the arrow between two columns — shows how many
// gate conditions guard that transition (0 = open, n = n conditions to pass).
function GateBadge({ n }) {
    const locked = n > 0;
    const color = locked ? '#80cbc4' : '#484f58';
    return (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px', flexShrink: 0, width: '48px', paddingTop: '14px' }}>
            <Arrow s={18} stroke={locked ? '#c9b8ff' : '#484f58'} />
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '3px', fontSize: '9px', color, background: locked ? 'rgba(128,203,196,.1)' : 'transparent', border: `1px solid ${locked ? 'rgba(128,203,196,.25)' : '#30363d'}`, borderRadius: '5px', padding: '2px 5px' }}>
                <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="5" y="11" width="14" height="10" rx="2" />
                    {locked ? <path d="M8 11V7a4 4 0 0 1 8 0v4" /> : <path d="M8 11V7a4 4 0 0 1 8 0" />}
                </svg>
                {n}
            </span>
        </div>
    );
}

function ColumnTile({ name, tasks, dotColor, selected, onSelect }) {
    const chipKey = tasks[0]?.key || tasks[0]?.id || null;
    if (selected) {
        return (
            <div onClick={() => onSelect(name)} style={{ position: 'relative', background: '#191620', border: '2px solid #c9b8ff', borderRadius: '11px', padding: '9px', width: '124px', flexShrink: 0, cursor: 'pointer', boxShadow: '0 0 0 4px rgba(201,184,255,.14),0 0 28px rgba(201,184,255,.22)' }}>
                <div style={{ position: 'absolute', top: '-9px', left: '50%', transform: 'translateX(-50%)', display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '8px', letterSpacing: '.08em', textTransform: 'uppercase', fontWeight: 700, color: '#0e1117', background: '#c9b8ff', borderRadius: '999px', padding: '2px 9px', whiteSpace: 'nowrap', boxShadow: '0 2px 6px rgba(0,0,0,.4)' }}>Selected</div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '6px', marginBottom: '8px', marginTop: '3px' }}>
                    <span style={{ fontSize: '11px', fontWeight: 700, color: '#f0f3f6' }}>{name}</span>
                    <Gear />
                </div>
                <div style={{ background: '#0a0c10', border: '1px solid #38bdf8', borderRadius: '6px', padding: '6px', display: 'flex', alignItems: 'center', gap: '6px', boxShadow: '0 0 12px rgba(56,189,248,.18)' }}>
                    <span style={{ width: '5px', height: '5px', borderRadius: '50%', background: '#38bdf8', animation: 'pulsedot 2800ms ease-in-out infinite' }} />
                    <span style={{ fontFamily: 'ui-monospace,SFMono-Regular,Menlo,monospace', fontSize: '8px', color: '#7dd3fc' }}>{chipKey || `${tasks.length} tasks`}</span>
                </div>
            </div>
        );
    }
    return (
        <div onClick={() => onSelect(name)} style={{ background: '#14161b', border: '1px solid #30363d', borderRadius: '10px', padding: '10px', width: '116px', flexShrink: 0, opacity: 0.5, cursor: 'pointer', transition: 'opacity .12s' }}
            onMouseEnter={(e) => (e.currentTarget.style.opacity = 0.8)} onMouseLeave={(e) => (e.currentTarget.style.opacity = 0.5)}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '6px', marginBottom: '8px' }}>
                <span style={{ fontSize: '11px', fontWeight: 600, color: '#f0f3f6' }}>{name}</span>
                <Gear />
            </div>
            <div style={{ background: '#0a0c10', border: '1px solid #30363d', borderRadius: '6px', padding: '6px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{ width: '5px', height: '5px', borderRadius: '50%', background: dotColor }} />
                <span style={{ fontSize: '9px', color: '#768390' }}>{tasks.length}</span>
            </div>
        </div>
    );
}

function ZoneHeader({ dot, label }) {
    return (
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', justifyContent: 'center', marginBottom: '14px' }}>
            <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: dot }} />
            <span style={{ fontSize: '10px', letterSpacing: '.1em', textTransform: 'uppercase', color: '#aeb6c0', fontWeight: 600 }}>{label}</span>
        </div>
    );
}

const StepIcon = ({ kind }) => {
    if (kind === 'assign') return <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: '18px', height: '18px', borderRadius: '50%', background: '#c9b8ff', fontSize: '9px', fontWeight: 700, color: '#0e1117' }}>R</span>;
    if (kind === 'dispatch') return <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#00bcd4" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 4l14 8-14 8V4z" /></svg>;
    return <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#00bcd4" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0" /></svg>;
};

function StepChip({ children }) {
    return (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', background: '#14161b', border: '1px solid #30363d', borderRadius: '10px', padding: '10px 13px' }}>{children}</span>
    );
}

function ProcessZone({ columnName, flow }) {
    const steps = processSteps(columnName, flow);
    return (
        <div style={{ background: 'rgba(0,188,212,.05)', border: '1px solid rgba(0,188,212,.22)', borderRadius: '14px', padding: '20px 18px' }}>
            <ZoneHeader dot="#00bcd4" label={`${columnName} · process · on enter, route the work`} />
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flexWrap: 'wrap', gap: '4px' }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', background: '#14161b', border: '1px solid #30363d', borderLeft: '2px solid #00bcd4', borderRadius: '10px', padding: '10px 13px' }}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#00bcd4" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4M10 17l5-5-5-5M15 12H3" /></svg>
                    <span style={{ fontSize: '12px', color: '#e8ebf0' }}>Enter <span style={{ fontFamily: 'ui-monospace,SFMono-Regular,Menlo,monospace', color: '#b1bac4' }}>{columnName}</span></span>
                </span>
                {steps.length === 0 ? (
                    <>
                        <div style={{ padding: '0 4px', flexShrink: 0 }}><Arrow /></div>
                        <StepChip><span style={{ fontSize: '12px', color: '#768390' }}>No process — tasks pass straight through</span></StepChip>
                    </>
                ) : steps.map((step, i) => (
                    <React.Fragment key={i}>
                        <div style={{ padding: '0 4px', flexShrink: 0 }}><Arrow /></div>
                        <StepChip>
                            <StepIcon kind={step.kind} />
                            <span style={{ fontSize: '12px', color: '#e8ebf0' }}>{step.label}</span>
                        </StepChip>
                    </React.Fragment>
                ))}
            </div>
        </div>
    );
}

function GateZone({ columnName, flow, project }) {
    const { to, conditions } = gateConditions(columnName, flow);
    return (
        <div style={{ background: 'rgba(128,203,196,.05)', border: '1px solid rgba(128,203,196,.26)', borderRadius: '14px', padding: '20px 18px' }}>
            <ZoneHeader dot="#80cbc4" label={`${columnName} · gate · on exit, can it leave?`} />
            {!to ? (
                <div style={{ textAlign: 'center', fontSize: '12px', color: '#768390' }}>Terminal column — nothing leaves here.</div>
            ) : (
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flexWrap: 'wrap', gap: '4px' }}>
                    {/* trigger */}
                    <div style={{ background: '#14161b', border: '1px solid #30363d', borderLeft: '2px solid #c9b8ff', borderRadius: '11px', padding: '13px 14px', width: '186px' }}>
                        <span style={{ display: 'inline-block', fontSize: '9px', letterSpacing: '.12em', textTransform: 'uppercase', color: '#c9b8ff', fontWeight: 700, background: 'rgba(201,184,255,.12)', borderRadius: '4px', padding: '2px 7px', marginBottom: '10px' }}>Trigger</span>
                        <div style={{ fontSize: '12px', color: '#b1bac4', marginBottom: '7px' }}>On transition</div>
                        <div style={{ display: 'inline-flex', alignItems: 'center', gap: '7px', fontFamily: 'ui-monospace,SFMono-Regular,Menlo,monospace', fontSize: '11px', color: '#c8cdd4', background: '#0a0c10', border: '1px solid #30363d', borderRadius: '6px', padding: '5px 9px' }}>{columnName} <span style={{ color: '#768390' }}>→</span> {to}</div>
                    </div>

                    <div style={{ padding: '0 6px', flexShrink: 0 }}><Arrow s={24} /></div>

                    {/* conditions */}
                    <div style={{ width: '272px' }}>
                        <div style={{ fontSize: '9px', letterSpacing: '.1em', textTransform: 'uppercase', color: '#768390', fontWeight: 600, marginBottom: '9px', textAlign: 'center' }}>
                            {conditions.length === 0 ? 'No conditions · always allows' : 'Conditions · all must pass'}
                        </div>
                        {conditions.length === 0 ? (
                            <div style={{ background: '#14161b', border: '1px solid #30363d', borderRadius: '9px', padding: '10px 12px', fontFamily: 'ui-monospace,SFMono-Regular,Menlo,monospace', fontSize: '11px', color: '#768390', textAlign: 'center' }}>return True</div>
                        ) : (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                {conditions.map((c, i) => (
                                    <React.Fragment key={c.id}>
                                        {i > 0 && (
                                            <div style={{ textAlign: 'center' }}><span style={{ fontFamily: 'ui-monospace,SFMono-Regular,Menlo,monospace', fontSize: '9px', letterSpacing: '.06em', color: '#a78bfa', background: 'rgba(124,77,255,.1)', borderRadius: '4px', padding: '2px 7px' }}>and</span></div>
                                        )}
                                        <div style={{ background: '#14161b', border: '1px solid #30363d', borderLeft: '2px solid #80cbc4', borderRadius: '9px', padding: '9px 12px' }}>
                                            <span
                                                title={c.source === 'evidence' ? 'verified — evidence fetched by the platform' : 'asserted — a task field, not independently verified'}
                                                style={{ display: 'inline-block', fontSize: '8px', letterSpacing: '.1em', textTransform: 'uppercase', fontWeight: 700, marginBottom: '5px', color: c.source === 'evidence' ? '#80cbc4' : '#ff9800' }}
                                            >{c.source === 'evidence' ? 'verified' : 'asserted'}</span>
                                            <div style={{ fontFamily: 'ui-monospace,SFMono-Regular,Menlo,monospace', fontSize: '11px', color: '#c8cdd4' }}>{c.expr}</div>
                                            <div style={{ fontSize: '10px', color: '#768390', marginTop: '3px' }}>{c.reason}</div>
                                        </div>
                                    </React.Fragment>
                                ))}
                            </div>
                        )}
                    </div>

                    <div style={{ padding: '0 6px', flexShrink: 0 }}><Arrow s={24} /></div>

                    {/* outcomes */}
                    <div style={{ width: '176px' }}>
                        <div style={{ fontSize: '9px', letterSpacing: '.1em', textTransform: 'uppercase', color: '#768390', fontWeight: 600, marginBottom: '9px', textAlign: 'center' }}>Outcome</div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                            <div style={{ background: 'rgba(46,204,113,.10)', border: '1px solid rgba(46,204,113,.45)', borderRadius: '10px', padding: '10px 12px' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '7px', marginBottom: '5px' }}><span style={{ width: '7px', height: '7px', borderRadius: '50%', background: '#2ecc71' }} /><span style={{ fontSize: '12.5px', fontWeight: 600, color: '#2ecc71' }}>Allow</span></div>
                                <div style={{ fontFamily: 'ui-monospace,SFMono-Regular,Menlo,monospace', fontSize: '10px', color: '#768390' }}>return True → {to}</div>
                            </div>
                            <div style={{ background: '#14161b', border: '1px solid #30363d', borderRadius: '10px', padding: '10px 12px', opacity: 0.5 }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '7px', marginBottom: '5px' }}><span style={{ width: '7px', height: '7px', borderRadius: '50%', background: '#f85149' }} /><span style={{ fontSize: '12.5px', fontWeight: 600, color: '#f85149' }}>Block</span></div>
                                <div style={{ fontFamily: 'ui-monospace,SFMono-Regular,Menlo,monospace', fontSize: '10px', color: '#768390' }}>else → stays in {columnName}</div>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}

/** The Workflow Engine visual canvas: board zone → process zone → gate zone. */
export function ColumnCanvas({ columnNames, tasksByColumn, selected, onSelect, flow, project }) {
    return (
        <div style={{ position: 'relative', overflow: 'auto', backgroundColor: '#0a0d14', backgroundImage: 'radial-gradient(#1a2333 1px, transparent 1px)', backgroundSize: '22px 22px', padding: '34px 26px' }}>
            {/* board zone */}
            <div style={{ position: 'relative', background: 'rgba(20,25,33,.55)', border: '1px solid #2a313c', borderRadius: '14px', padding: '20px 18px 16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', justifyContent: 'center', marginBottom: '16px' }}>
                    <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#c9b8ff' }} />
                    <span style={{ fontSize: '10px', letterSpacing: '.1em', textTransform: 'uppercase', color: '#aeb6c0', fontWeight: 600 }}>The board · every column has a process &amp; a gate</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'center', flexWrap: 'wrap', gap: 0, marginBottom: '6px' }}>
                    {columnNames.map((name, i) => {
                        const tasks = tasksByColumn[name] || [];
                        const badge = i < columnNames.length - 1 ? gateConditions(name, flow) : null;
                        return (
                            <React.Fragment key={name}>
                                <ColumnTile name={name} tasks={tasks} dotColor={DOT_RING[i % DOT_RING.length]} selected={selected === name} onSelect={onSelect} />
                                {badge && <GateBadge n={badge.to === columnNames[i + 1] ? badge.conditions.length : 0} />}
                            </React.Fragment>
                        );
                    })}
                </div>
                <div style={{ textAlign: 'center', marginTop: '4px' }}>
                    <span style={{ fontSize: '9.5px', color: '#768390' }}>Selecting the <span style={{ color: '#c9b8ff' }}>{selected}</span> column — its process and gate are shown below</span>
                </div>
            </div>

            <DownArrow />
            <ProcessZone columnName={selected} flow={flow} />
            <DownArrow />
            <GateZone columnName={selected} flow={flow} project={project} />
        </div>
    );
}
