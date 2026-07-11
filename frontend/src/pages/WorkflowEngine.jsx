import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { ROUTES } from '../routes';

// Public marketing page for the Workflow Engine, ported from the design
// concept `design/agentira-zip/Workflow Engine.dc.html`. Colors come from
// the imported design-system tokens (src/tokens/colors.css).

const mono = 'var(--font-mono)';

function GearIcon() {
    return (
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="var(--accent-cyan)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
    );
}

function ArrowRightIcon({ size = 20, color = 'var(--border-active)' }) {
    return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 12h14M13 6l6 6-6 6" />
        </svg>
    );
}

function LockBadge({ count, active }) {
    const fg = active ? 'var(--surface-base)' : 'var(--brand-teal)';
    return (
        <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 9, padding: '2px 5px',
            fontWeight: active ? 600 : 400,
            color: active ? 'var(--surface-base)' : 'var(--brand-teal)',
            background: active ? 'var(--brand-teal)' : 'var(--tint-teal)',
            border: `1px solid ${active ? 'var(--brand-teal)' : 'rgba(128,203,196,.25)'}`, borderRadius: 5,
        }}>
            <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke={fg} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                <rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" />
            </svg>
            {count}
        </span>
    );
}

function BoardColumn({ name, dotColor, barWidth }) {
    return (
        <div style={{ background: 'var(--surface-raised)', border: '1px solid var(--border-subtle)', borderRadius: 10, padding: 10, width: 116, flexShrink: 0, opacity: 0.45 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6, marginBottom: 8 }}>
                <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-primary)', whiteSpace: 'nowrap' }}>{name}</span>
                <GearIcon />
            </div>
            <div style={{ background: 'var(--surface-sunken)', border: '1px solid var(--border-subtle)', borderRadius: 6, padding: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 5, height: 5, borderRadius: '50%', background: dotColor }} />
                <span style={{ height: 2, width: barWidth, background: 'var(--border-subtle)', borderRadius: 2 }} />
            </div>
        </div>
    );
}

function ColumnGap({ count, active }) {
    return (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, flexShrink: 0, width: active ? 52 : 46, paddingTop: 14, opacity: active ? 1 : 0.45 }}>
            <ArrowRightIcon size={18} color={active ? 'var(--brand-lavender)' : 'var(--border-active)'} />
            <LockBadge count={count} active={active} />
        </div>
    );
}

function ProcessStep({ children, accent }) {
    return (
        <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 8, background: 'var(--surface-raised)',
            border: '1px solid var(--border-subtle)', borderLeft: accent ? '2px solid var(--accent-cyan)' : '1px solid var(--border-subtle)',
            borderRadius: 10, padding: '10px 13px',
        }}>
            {children}
        </span>
    );
}

function Condition({ children }) {
    return (
        <div style={{ background: 'var(--surface-raised)', border: '1px solid var(--border-subtle)', borderLeft: '2px solid var(--brand-teal)', borderRadius: 9, padding: '9px 12px' }}>
            <span style={{ display: 'inline-block', fontSize: 8, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--brand-teal)', fontWeight: 700, marginBottom: 5 }}>Condition</span>
            <div style={{ fontFamily: mono, fontSize: 11, color: '#c8cdd4' }}>{children}</div>
        </div>
    );
}

function AndSep() {
    return (
        <div style={{ textAlign: 'center' }}>
            <span style={{ fontFamily: mono, fontSize: 9, letterSpacing: '.06em', color: '#a78bfa', background: 'var(--tint-purple)', borderRadius: 4, padding: '2px 7px' }}>and</span>
        </div>
    );
}

function SectionKicker({ dot, label }) {
    return (
        <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 18 }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: dot }} />
            <span style={{ fontSize: 12, letterSpacing: '.14em', textTransform: 'uppercase', color: '#aeb6c0', fontWeight: 600 }}>{label}</span>
        </div>
    );
}

// Starlark / Python snippets, token-colored per the concept's palette.
const kw = { color: '#a78bfa' };
const fn = { color: 'var(--pulse-blue-bright)' };
const str = { color: 'var(--brand-teal)' };
const op = { color: 'var(--text-tertiary)' };
const lit = { color: 'var(--warning)' };
const cmt = { color: '#5b636e' };
const num = { color: 'var(--pulse-blue-bright)' };

function ReviewStarCode() {
    const lines = [
        <span style={cmt}># Review column · acme/billing-api</span>,
        <>&nbsp;</>,
        <span style={{ color: 'var(--accent-cyan)' }}># ===  PROCESS  — runs when a task enters  ===</span>,
        <><span style={kw}>def</span> <span style={fn}>on_enter</span>(task, board):</>,
        <>{'    '}task.assign(role<span style={op}>=</span><span style={str}>"reviewer"</span>)</>,
        <>{'    '}task.dispatch_run()</>,
        <>{'    '}task.notify(watchers<span style={op}>=</span><span style={lit}>True</span>)</>,
        <>&nbsp;</>,
        <span style={{ color: 'var(--brand-teal)' }}># ===  GATE  — verifies before it can leave  ===</span>,
        <><span style={kw}>def</span> <span style={fn}>validate_transition</span>(task, evidence, user):</>,
        <>{'    '}<span style={cmt}># evidence is fetched by the platform, not the agent</span></>,
        <>{'    '}<span style={kw}>if</span> evidence.github_pr.state <span style={op}>!=</span> <span style={str}>"merged"</span>:</>,
        <>{'        '}<span style={kw}>return</span> <span style={lit}>False</span>, <span style={str}>"PR must be merged"</span></>,
        <>{'    '}<span style={kw}>if</span> <span style={kw}>not</span> evidence.ci.passed:</>,
        <>{'        '}<span style={kw}>return</span> <span style={lit}>False</span>, <span style={str}>"CI must be green"</span></>,
        <>{'    '}<span style={kw}>if</span> evidence.coverage <span style={op}>&lt;</span> <span style={num}>0.85</span>:</>,
        <>{'        '}<span style={kw}>return</span> <span style={lit}>False</span>, <span style={str}>"coverage below 85%"</span></>,
        <>{'    '}<span style={kw}>return</span> <span style={{ color: 'var(--success)' }}>True</span>, <span style={str}>""</span></>,
    ];
    return (
        <div style={{ display: 'flex', fontFamily: mono, fontSize: 12.5, lineHeight: 1.8 }}>
            <div style={{ textAlign: 'right', color: '#3a434f', paddingRight: 16, borderRight: '1px solid #21272f', userSelect: 'none' }}>
                {lines.map((_, i) => <div key={i}>{i + 1}</div>)}
            </div>
            <div style={{ paddingLeft: 16, whiteSpace: 'pre', color: '#c8cdd4', overflowX: 'auto' }}>
                {lines.map((l, i) => <div key={i}>{l}</div>)}
            </div>
        </div>
    );
}

function AgentiraMark({ size = 30 }) {
    return (
        <svg width={size} height={size} viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" aria-label="Agentira">
            <defs>
                <linearGradient id="agwe" x1="8" y1="8" x2="56" y2="56" gradientUnits="userSpaceOnUse">
                    <stop stopColor="#c9b8ff" /><stop offset="1" stopColor="#80cbc4" />
                </linearGradient>
            </defs>
            <rect width="64" height="64" rx="16" fill="url(#agwe)" />
            <path d="M22 44 L32 19 L42 44 M26 36 H38" stroke="#0e1117" strokeWidth="3.6" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        </svg>
    );
}

const grantedChip = { fontFamily: mono, fontSize: 11, color: '#c8cdd4', background: 'var(--surface-card)', border: '1px solid var(--border-subtle)', borderRadius: 6, padding: '4px 9px' };
const deniedChip = { fontFamily: mono, fontSize: 11, color: '#5b636e', background: 'var(--surface-base)', border: '1px dashed var(--border-subtle)', borderRadius: 6, padding: '4px 9px', textDecoration: 'line-through' };
const evidenceRow = { display: 'flex', alignItems: 'center', gap: 9, background: 'var(--surface-base)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: '9px 11px' };

export function WorkflowEngine() {
    const [view, setView] = useState('visual');
    const isVisual = view === 'visual';
    const btnBase = { fontFamily: 'inherit', fontSize: 11, borderRadius: 6, padding: '4px 12px', margin: 0, cursor: 'pointer', lineHeight: 1.5 };
    const activeBtn = { ...btnBase, fontWeight: 600, color: 'var(--surface-base)', background: 'var(--brand-lavender)', border: '1px solid var(--brand-lavender)' };
    const idleBtn = { ...btnBase, fontWeight: 500, color: 'var(--text-secondary)', background: 'transparent', border: '1px solid var(--border-subtle)' };

    return (
        <div className="h-full overflow-y-auto" style={{ background: 'var(--surface-base)', color: 'var(--text-primary)', overflowX: 'hidden' }}>

            {/* Nav */}
            <header style={{ position: 'sticky', top: 0, zIndex: 50, backdropFilter: 'saturate(140%) blur(12px)', background: 'rgba(14,17,23,.82)', borderBottom: '1px solid var(--border-subtle)' }}>
                <div style={{ maxWidth: 1120, margin: '0 auto', padding: '0 32px', height: 60, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 24 }}>
                    <Link to={ROUTES.WELCOME} style={{ display: 'flex', alignItems: 'center', gap: 11, textDecoration: 'none' }}>
                        <AgentiraMark />
                        <span style={{ fontSize: 17, fontWeight: 700, letterSpacing: '-0.015em', color: 'var(--text-primary)' }}>Agentira</span>
                        <span style={{ fontSize: 13, color: 'var(--text-tertiary)', marginLeft: 2 }}>/ Workflow Engine</span>
                    </Link>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                        <Link to={ROUTES.WELCOME} style={{ fontSize: 13.5, color: '#c8cdd4', textDecoration: 'none', padding: '8px 6px' }}>&larr; Back to home</Link>
                        <Link to={ROUTES.SIGNUP} style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--surface-base)', background: 'var(--brand-lavender)', border: '1px solid var(--brand-lavender)', borderRadius: 8, padding: '8px 16px', textDecoration: 'none' }}>Start free</Link>
                    </div>
                </div>
            </header>

            {/* Hero */}
            <section style={{ maxWidth: 1120, margin: '0 auto', padding: '84px 32px 70px' }}>
                <div style={{ display: 'inline-flex', alignItems: 'center', gap: 9, border: '1px solid var(--border-subtle)', background: 'var(--surface-raised)', borderRadius: 999, padding: '6px 13px', marginBottom: 26 }}>
                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--brand-teal)' }} />
                    <span style={{ fontSize: 12, letterSpacing: '.1em', textTransform: 'uppercase', color: '#aeb6c0', fontWeight: 500 }}>The Workflow Engine</span>
                </div>
                <h1 style={{ margin: '0 0 22px', fontSize: 'clamp(34px,4.6vw,56px)', fontWeight: 600, letterSpacing: '-0.03em', lineHeight: 1.05, color: 'var(--text-primary)', maxWidth: '18ch' }}>
                    Rules you write. Evidence the agent can't touch.
                </h1>
                <p style={{ margin: 0, fontSize: 18, lineHeight: 1.62, color: 'var(--text-secondary)', maxWidth: '64ch' }}>
                    The engine runs two kinds of rules you control: <strong style={{ color: '#e8ebf0', fontWeight: 600 }}>process</strong> &mdash; who does what when a task lands in a column &mdash; and <strong style={{ color: '#e8ebf0', fontWeight: 600 }}>verification</strong> &mdash; the gate that decides whether it can leave. The agent does the work, but it's the platform, never the agent, that gathers the evidence behind a gate.
                </p>
            </section>

            {/* Workflow canvas */}
            <section style={{ maxWidth: 1120, margin: '0 auto', padding: '0 32px 90px' }}>
                <div style={{ background: 'var(--surface-raised)', border: '1px solid var(--border-subtle)', borderRadius: 16, boxShadow: '0 30px 80px rgba(0,0,0,.55)', overflow: 'hidden' }}>
                    {/* toolbar */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 11, padding: '13px 16px', borderBottom: '1px solid var(--border-subtle)', background: 'var(--surface-nav)' }}>
                        <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 22, height: 22, borderRadius: 6, background: 'var(--tint-teal)' }}>
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--brand-teal)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <circle cx="6" cy="6" r="2.5" /><circle cx="18" cy="18" r="2.5" /><path d="M8.5 6H15a3 3 0 0 1 3 3v6.5" />
                            </svg>
                        </span>
                        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>Workflow Engine</span>
                        <span style={{ fontFamily: mono, fontSize: 11, color: 'var(--text-tertiary)' }}>acme/billing-api &middot; review &rarr; done</span>
                        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 7 }}>
                            <button style={{ fontFamily: 'inherit', display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11, fontWeight: 600, color: 'var(--brand-lavender)', background: 'var(--accent-subtle)', border: '1px solid rgba(201,184,255,.3)', borderRadius: 6, padding: '4px 11px', margin: 0, cursor: 'pointer', lineHeight: 1.5 }}>
                                <svg width="11" height="11" viewBox="0 0 24 24" fill="var(--brand-lavender)" stroke="none"><path d="M12 2.5l1.9 5.7 5.7 1.9-5.7 1.9L12 17.7l-1.9-5.7L4.4 10l5.7-1.9z" /></svg>
                                Build with AI
                            </button>
                            <span style={{ width: 1, height: 18, background: 'var(--border-subtle)', margin: '0 2px' }} />
                            <button onClick={() => setView('visual')} style={isVisual ? activeBtn : idleBtn}>Visual</button>
                            <button onClick={() => setView('code')} style={isVisual ? idleBtn : activeBtn}>Code</button>
                        </div>
                    </div>

                    {isVisual ? (
                        <div style={{ position: 'relative', overflow: 'hidden', backgroundColor: '#0a0d14', backgroundImage: 'radial-gradient(#1a2333 1px, transparent 1px)', backgroundSize: '22px 22px', padding: '34px 26px' }}>
                            {/* board */}
                            <div style={{ position: 'relative', background: 'rgba(20,25,33,.55)', border: '1px solid #2a313c', borderRadius: 14, padding: '20px 18px 16px' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'center', marginBottom: 16 }}>
                                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--brand-lavender)' }} />
                                    <span style={{ fontSize: 10, letterSpacing: '.1em', textTransform: 'uppercase', color: '#aeb6c0', fontWeight: 600 }}>The board &middot; every column has a process &amp; a gate</span>
                                </div>
                                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'center', flexWrap: 'wrap', gap: 0, marginBottom: 6 }}>
                                    <BoardColumn name="Backlog" dotColor="var(--text-tertiary)" barWidth="80%" />
                                    <ColumnGap count={1} />
                                    <BoardColumn name="Todo" dotColor="#58a6ff" barWidth="70%" />
                                    <ColumnGap count={1} />
                                    <BoardColumn name={'In Progress'} dotColor="var(--warning)" barWidth="60%" />
                                    <ColumnGap count={2} />
                                    {/* Review — selected */}
                                    <div style={{ position: 'relative', background: '#191620', border: '2px solid var(--brand-lavender)', borderRadius: 11, padding: 9, width: 120, flexShrink: 0, boxShadow: '0 0 0 4px rgba(201,184,255,.14),0 0 28px rgba(201,184,255,.22)' }}>
                                        <div style={{ position: 'absolute', top: -9, left: '50%', transform: 'translateX(-50%)', display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 8, letterSpacing: '.08em', textTransform: 'uppercase', fontWeight: 700, color: 'var(--surface-base)', background: 'var(--brand-lavender)', borderRadius: 999, padding: '2px 9px', whiteSpace: 'nowrap', boxShadow: '0 2px 6px rgba(0,0,0,.4)' }}>Selected</div>
                                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6, marginBottom: 8, marginTop: 3 }}>
                                            <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-primary)' }}>Review</span>
                                            <GearIcon />
                                        </div>
                                        <div style={{ background: 'var(--surface-sunken)', border: '1px solid var(--pulse-blue)', borderRadius: 6, padding: 6, display: 'flex', alignItems: 'center', gap: 6, boxShadow: '0 0 12px rgba(56,189,248,.18)' }}>
                                            <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--pulse-blue)', animation: 'agentira-pulsedot 2800ms ease-in-out infinite' }} />
                                            <span style={{ fontFamily: mono, fontSize: 8, color: 'var(--pulse-blue-bright)' }}>AP-131</span>
                                        </div>
                                    </div>
                                    <ColumnGap count={3} active />
                                    <BoardColumn name="Done" dotColor="var(--success)" barWidth="50%" />
                                </div>
                                <div style={{ textAlign: 'center', marginTop: 4 }}>
                                    <span style={{ fontSize: 9.5, color: 'var(--text-tertiary)' }}>Selecting the <span style={{ color: 'var(--brand-lavender)' }}>Review</span> column &mdash; its process and gate are shown below</span>
                                </div>
                            </div>

                            <div style={{ display: 'flex', justifyContent: 'center', padding: '11px 0' }}>
                                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#3a434f" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5v14M6 13l6 6 6-6" /></svg>
                            </div>

                            {/* process */}
                            <div style={{ background: 'rgba(0,188,212,.05)', border: '1px solid rgba(0,188,212,.22)', borderRadius: 14, padding: '20px 18px' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'center', marginBottom: 14 }}>
                                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--accent-cyan)' }} />
                                    <span style={{ fontSize: 10, letterSpacing: '.1em', textTransform: 'uppercase', color: '#aeb6c0', fontWeight: 600 }}>Review &middot; process &middot; on enter, route the work</span>
                                </div>
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
                                    <ProcessStep accent>
                                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent-cyan)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4M10 17l5-5-5-5M15 12H3" /></svg>
                                        <span style={{ fontSize: 12, color: '#e8ebf0' }}>Enter <span style={{ fontFamily: mono, color: 'var(--text-secondary)' }}>Review</span></span>
                                    </ProcessStep>
                                    <div style={{ padding: '0 4px', flexShrink: 0 }}><ArrowRightIcon /></div>
                                    <ProcessStep>
                                        <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 18, height: 18, borderRadius: '50%', background: 'var(--brand-lavender)', fontSize: 9, fontWeight: 700, color: 'var(--surface-base)' }}>R</span>
                                        <span style={{ fontSize: 12, color: '#e8ebf0' }}>Assign Reviewer</span>
                                    </ProcessStep>
                                    <div style={{ padding: '0 4px', flexShrink: 0 }}><ArrowRightIcon /></div>
                                    <ProcessStep>
                                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--accent-cyan)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 4l14 8-14 8V4z" /></svg>
                                        <span style={{ fontSize: 12, color: '#e8ebf0' }}>Dispatch run</span>
                                    </ProcessStep>
                                    <div style={{ padding: '0 4px', flexShrink: 0 }}><ArrowRightIcon /></div>
                                    <ProcessStep>
                                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--accent-cyan)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0" /></svg>
                                        <span style={{ fontSize: 12, color: '#e8ebf0' }}>Notify</span>
                                    </ProcessStep>
                                </div>
                            </div>

                            <div style={{ display: 'flex', justifyContent: 'center', padding: '11px 0' }}>
                                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#3a434f" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5v14M6 13l6 6 6-6" /></svg>
                            </div>

                            {/* gate */}
                            <div style={{ background: 'rgba(128,203,196,.05)', border: '1px solid rgba(128,203,196,.26)', borderRadius: 14, padding: '20px 18px' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'center', marginBottom: 16 }}>
                                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--brand-teal)' }} />
                                    <span style={{ fontSize: 10, letterSpacing: '.1em', textTransform: 'uppercase', color: '#aeb6c0', fontWeight: 600 }}>Review &middot; gate &middot; on exit, can it leave?</span>
                                </div>
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flexWrap: 'wrap', gap: 4 }}>
                                    {/* trigger */}
                                    <div style={{ background: 'var(--surface-raised)', border: '1px solid var(--border-subtle)', borderLeft: '2px solid var(--brand-lavender)', borderRadius: 11, padding: '13px 14px', width: 186 }}>
                                        <span style={{ display: 'inline-block', fontSize: 9, letterSpacing: '.12em', textTransform: 'uppercase', color: 'var(--brand-lavender)', fontWeight: 700, background: 'rgba(201,184,255,.12)', borderRadius: 4, padding: '2px 7px', marginBottom: 10 }}>Trigger</span>
                                        <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 7 }}>On transition</div>
                                        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontFamily: mono, fontSize: 11, color: '#c8cdd4', background: 'var(--surface-sunken)', border: '1px solid var(--border-subtle)', borderRadius: 6, padding: '5px 9px' }}>
                                            review <span style={{ color: 'var(--text-tertiary)' }}>&rarr;</span> done
                                        </div>
                                    </div>

                                    <div style={{ padding: '0 6px', flexShrink: 0 }}><ArrowRightIcon size={24} /></div>

                                    {/* conditions */}
                                    <div style={{ width: 262 }}>
                                        <div style={{ fontSize: 9, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--text-tertiary)', fontWeight: 600, marginBottom: 9, textAlign: 'center' }}>Conditions &middot; all must pass</div>
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                                            <Condition>evidence.github_pr.state <span style={op}>==</span> <span style={str}>"merged"</span></Condition>
                                            <AndSep />
                                            <Condition>evidence.ci.passed</Condition>
                                            <AndSep />
                                            <Condition>evidence.coverage <span style={op}>&gt;=</span> <span style={num}>0.85</span></Condition>
                                        </div>
                                    </div>

                                    <div style={{ padding: '0 6px', flexShrink: 0 }}><ArrowRightIcon size={24} /></div>

                                    {/* outcomes */}
                                    <div style={{ width: 176 }}>
                                        <div style={{ fontSize: 9, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--text-tertiary)', fontWeight: 600, marginBottom: 9, textAlign: 'center' }}>Outcome</div>
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                            <div style={{ background: 'rgba(46,204,113,.10)', border: '1px solid rgba(46,204,113,.45)', borderRadius: 10, padding: '10px 12px' }}>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 5 }}>
                                                    <span style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--success)' }} />
                                                    <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--success)' }}>Allow</span>
                                                </div>
                                                <div style={{ fontFamily: mono, fontSize: 10, color: 'var(--text-tertiary)' }}>return True &rarr; Done</div>
                                            </div>
                                            <div style={{ background: 'var(--surface-raised)', border: '1px solid var(--border-subtle)', borderRadius: 10, padding: '10px 12px', opacity: 0.5 }}>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 5 }}>
                                                    <span style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--danger)' }} />
                                                    <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--danger)' }}>Block</span>
                                                </div>
                                                <div style={{ fontFamily: mono, fontSize: 10, color: 'var(--text-tertiary)' }}>else &rarr; stays in Review</div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    ) : (
                        <div style={{ background: 'var(--surface-sunken)', padding: '22px 24px', minHeight: 332 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
                                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontFamily: mono, fontSize: 11, color: '#c8cdd4', background: 'var(--surface-nav)', border: '1px solid var(--border-subtle)', borderRadius: 6, padding: '4px 10px' }}>
                                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--brand-lavender)' }} />
                                    review.star
                                </span>
                                <span style={{ fontSize: 10, fontWeight: 600, letterSpacing: '.04em', color: 'var(--brand-teal)', background: 'rgba(128,203,196,.12)', border: '1px solid rgba(128,203,196,.3)', borderRadius: 5, padding: '3px 8px' }}>Starlark</span>
                                <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>generated from the visual editor &middot; read-only</span>
                            </div>
                            <ReviewStarCode />
                        </div>
                    )}
                </div>
                <p style={{ margin: '16px auto 0', fontSize: 13, color: 'var(--text-tertiary)', textAlign: 'center', maxWidth: '60ch' }}>
                    Every column on the board gets its own rules: a <strong style={{ color: '#aeb6c0', fontWeight: 600 }}>process</strong> that routes work in on arrival, and a Starlark <strong style={{ color: '#aeb6c0', fontWeight: 600 }}>gate</strong> that verifies the evidence before work is allowed out. Here, the Review column is selected.
                </p>
            </section>

            {/* Three views */}
            <section style={{ borderTop: '1px solid var(--border-subtle)', background: 'var(--surface-base)' }}>
                <div style={{ maxWidth: 1120, margin: '0 auto', padding: '96px 32px 90px' }}>
                    <div style={{ maxWidth: 640, marginBottom: 46 }}>
                        <SectionKicker dot="var(--brand-lavender)" label="One rule, three views" />
                        <h2 style={{ margin: '0 0 18px', fontSize: 'clamp(28px,3.4vw,40px)', fontWeight: 600, letterSpacing: '-0.025em', lineHeight: 1.12, color: 'var(--text-primary)' }}>Build it however you think.</h2>
                        <p style={{ margin: 0, fontSize: 16.5, lineHeight: 1.62, color: 'var(--text-secondary)', maxWidth: '58ch' }}>Visual, AI, or code &mdash; they're the same rule underneath. Each view is just a different lens on it, and an edit in one shows up in the others.</p>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(280px,1fr))', gap: 20 }}>
                        {[{
                            name: 'Visual', accent: 'var(--brand-lavender)', tint: 'var(--tint-lavender)',
                            icon: <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="var(--brand-lavender)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="6" cy="6" r="2.5" /><circle cx="18" cy="18" r="2.5" /><path d="M8.5 6H15a3 3 0 0 1 3 3v6.5" /></svg>,
                            desc: 'A drag-and-drop node editor. Read the flow and adjust conditions, branches and outcomes — no code, so non-technical owners can follow it.',
                            best: 'reading & tweaking',
                        }, {
                            name: 'AI', accent: 'var(--brand-teal)', tint: 'var(--tint-teal)',
                            icon: <svg width="17" height="17" viewBox="0 0 24 24" fill="var(--brand-teal)" stroke="none"><path d="M12 2.5l1.9 5.7 5.7 1.9-5.7 1.9L12 17.7l-1.9-5.7L4.4 10l5.7-1.9z" /><path d="M19 3l.6 1.8 1.8.6-1.8.6L19 8l-.6-1.8L16.6 5.6 18.4 5z" /></svg>,
                            desc: 'Describe the rule in plain English. Agentira compiles it to Starlark and draws the nodes for you — a first draft in seconds.',
                            best: 'starting fast',
                        }, {
                            name: 'Code', accent: 'var(--accent-cyan)', tint: 'var(--tint-cyan)',
                            icon: <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="var(--accent-cyan)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M8 6 3 12l5 6M16 6l5 6-5 6" /></svg>,
                            desc: 'Drop into Starlark for everyday gates, or custom Python for richer logic and bespoke evidence sources. Full control when you need it.',
                            best: 'precision & power',
                        }].map((v) => (
                            <div key={v.name} style={{ background: 'var(--surface-card)', border: '1px solid var(--border-subtle)', borderTop: `2px solid ${v.accent}`, borderRadius: 14, padding: 26 }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 11, marginBottom: 14 }}>
                                    <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 34, height: 34, borderRadius: 9, background: v.tint }}>{v.icon}</span>
                                    <div>
                                        <div style={{ fontSize: 11, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--text-tertiary)', fontWeight: 600 }}>View</div>
                                        <div style={{ fontSize: 18, fontWeight: 600, letterSpacing: '-0.01em', color: 'var(--text-primary)' }}>{v.name}</div>
                                    </div>
                                </div>
                                <p style={{ margin: '0 0 14px', fontSize: 14.5, lineHeight: 1.6, color: 'var(--text-secondary)' }}>{v.desc}</p>
                                <div style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>Best for <span style={{ color: '#c8cdd4' }}>{v.best}</span></div>
                            </div>
                        ))}
                    </div>

                    <div style={{ marginTop: 28, display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'center', gap: 14, background: 'var(--surface-raised)', border: '1px solid var(--border-subtle)', borderRadius: 14, padding: '18px 24px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                            <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--brand-lavender)' }}>Visual</span>
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--text-tertiary)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 8h14M13 4l4 4-4 4" /><path d="M21 16H7M11 20l-4-4 4-4" /></svg>
                            <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--brand-teal)' }}>AI</span>
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--text-tertiary)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 8h14M13 4l4 4-4 4" /><path d="M21 16H7M11 20l-4-4 4-4" /></svg>
                            <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--accent-cyan)' }}>Code</span>
                        </div>
                        <span style={{ fontSize: 14, color: 'var(--text-secondary)', textAlign: 'center' }}>Fully interchangeable &mdash; switch views anytime, and every edit writes the same underlying rule.</span>
                    </div>
                </div>
            </section>

            {/* Separation of duties */}
            <section style={{ borderTop: '1px solid var(--border-subtle)', background: '#0c0f14' }}>
                <div style={{ maxWidth: 1120, margin: '0 auto', padding: '96px 32px 92px' }}>
                    <div style={{ maxWidth: 640, marginBottom: 48 }}>
                        <SectionKicker dot="var(--brand-teal)" label="Separation of duties" />
                        <h2 style={{ margin: '0 0 18px', fontSize: 'clamp(28px,3.4vw,40px)', fontWeight: 600, letterSpacing: '-0.025em', lineHeight: 1.12, color: 'var(--text-primary)' }}>The agent can't grade its own homework.</h2>
                        <p style={{ margin: 0, fontSize: 16.5, lineHeight: 1.62, color: 'var(--text-secondary)', maxWidth: '58ch' }}>The tools that fetch evidence and evaluate gates live in the platform, behind the agent's reach. An agent can open a PR &mdash; it cannot tell the system the PR is merged. The system checks for itself.</p>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', gap: 0, alignItems: 'stretch', background: 'var(--surface-raised)', border: '1px solid var(--border-subtle)', borderRadius: 16, overflow: 'hidden' }}>
                        {/* agent side */}
                        <div style={{ padding: 26, minWidth: 260 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 18 }}>
                                <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 30, height: 30, borderRadius: 8, background: 'var(--tint-cyan)' }}>
                                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--accent-cyan)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M8 6 3 12l5 6M16 6l5 6-5 6" /></svg>
                                </span>
                                <div style={{ lineHeight: 1.25 }}>
                                    <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>Agent runtime</div>
                                    <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>does the work</div>
                                </div>
                            </div>
                            <div style={{ fontSize: 10, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--text-tertiary)', fontWeight: 600, marginBottom: 11 }}>Granted</div>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 7, marginBottom: 20 }}>
                                {['Read', 'Edit', 'Bash', 'git push', 'open PR'].map((t) => <span key={t} style={grantedChip}>{t}</span>)}
                            </div>
                            <div style={{ fontSize: 10, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--text-tertiary)', fontWeight: 600, marginBottom: 11 }}>No access</div>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 7 }}>
                                {['fetch_evidence', 'set_status', 'pass_gate'].map((t) => <span key={t} style={deniedChip}>{t}</span>)}
                            </div>
                        </div>

                        {/* barrier */}
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 10, padding: '0 14px', background: 'var(--surface-base)', borderLeft: '1px dashed var(--border-active)', borderRight: '1px dashed var(--border-active)', position: 'relative' }}>
                            <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 38, height: 38, borderRadius: '50%', background: 'var(--surface-card)', border: '1px solid var(--border-active)' }}>
                                <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="var(--text-tertiary)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg>
                            </span>
                            <span style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)', fontSize: 10, letterSpacing: '.14em', textTransform: 'uppercase', color: '#5b636e', fontWeight: 600 }}>trust boundary</span>
                        </div>

                        {/* system side */}
                        <div style={{ padding: 26, minWidth: 260, background: '#16191f' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 18 }}>
                                <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 30, height: 30, borderRadius: 8, background: 'var(--tint-teal)' }}>
                                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--brand-teal)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2 4 6v6c0 5 8 8 8 8s8-3 8-8V6l-8-4Z" /><path d="m9 12 2 2 4-4" /></svg>
                                </span>
                                <div style={{ lineHeight: 1.25 }}>
                                    <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>Platform</div>
                                    <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>verifies independently</div>
                                </div>
                            </div>
                            <div style={{ fontSize: 10, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--text-tertiary)', fontWeight: 600, marginBottom: 11 }}>Fetches with its own credentials</div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
                                {[['GitHub PR state', 'var(--success)'], ['CI run result', 'var(--success)'], ['Commit SHA exists', 'var(--success)'], ['+ your custom evidence', 'var(--brand-teal)']].map(([label, dot]) => (
                                    <div key={label} style={evidenceRow}>
                                        <span style={{ width: 6, height: 6, borderRadius: '50%', background: dot }} />
                                        <span style={{ fontSize: 12.5, color: '#e8ebf0' }}>{label}</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                </div>
            </section>

            {/* Scriptable rules */}
            <section style={{ borderTop: '1px solid var(--border-subtle)', background: 'var(--surface-base)' }}>
                <div style={{ maxWidth: 1120, margin: '0 auto', padding: '96px 32px 92px' }}>
                    <div style={{ maxWidth: 640, marginBottom: 48 }}>
                        <SectionKicker dot="var(--brand-lavender)" label="Scriptable rules" />
                        <h2 style={{ margin: '0 0 18px', fontSize: 'clamp(28px,3.4vw,40px)', fontWeight: 600, letterSpacing: '-0.025em', lineHeight: 1.12, color: 'var(--text-primary)' }}>Starlark for everyday gates. Python when you need more.</h2>
                        <p style={{ margin: 0, fontSize: 16.5, lineHeight: 1.62, color: 'var(--text-secondary)', maxWidth: '58ch' }}>Most rules are a few lines of Starlark &mdash; safe, deterministic, and capped at 50ms in a sandbox. When a customer needs richer logic or a bespoke evidence source, drop to custom Python that runs server-side, never in the agent.</p>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(340px,1fr))', gap: 22 }}>
                        <div style={{ background: 'var(--surface-raised)', border: '1px solid var(--border-subtle)', borderRadius: 14, overflow: 'hidden' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '13px 16px', borderBottom: '1px solid var(--border-subtle)' }}>
                                <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>Starlark gate</span>
                                <span style={{ fontSize: 10.5, color: 'var(--brand-teal)', background: 'rgba(128,203,196,.12)', borderRadius: 999, padding: '3px 9px' }}>sandboxed &middot; &lt;50ms</span>
                            </div>
                            <div style={{ padding: 16, fontFamily: mono, fontSize: 12.5, lineHeight: 1.7, background: 'var(--surface-sunken)' }}>
                                <div><span style={kw}>def</span> <span style={fn}>validate_transition</span>(task, evidence, user):</div>
                                <div style={{ paddingLeft: 18 }}><span style={kw}>if</span> <span style={kw}>not</span> evidence.github_pr.state <span style={op}>==</span> <span style={str}>"merged"</span>:</div>
                                <div style={{ paddingLeft: 36 }}><span style={kw}>return</span> <span style={lit}>False</span>, <span style={str}>"PR must be merged"</span></div>
                                <div style={{ paddingLeft: 18 }}><span style={kw}>if</span> <span style={kw}>not</span> evidence.ci.passed:</div>
                                <div style={{ paddingLeft: 36 }}><span style={kw}>return</span> <span style={lit}>False</span>, <span style={str}>"CI must be green"</span></div>
                                <div style={{ paddingLeft: 18 }}><span style={kw}>return</span> <span style={{ color: 'var(--success)' }}>True</span>, <span style={str}>""</span></div>
                            </div>
                        </div>

                        <div style={{ background: 'var(--surface-raised)', border: '1px solid var(--border-subtle)', borderRadius: 14, overflow: 'hidden' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '13px 16px', borderBottom: '1px solid var(--border-subtle)' }}>
                                <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>Custom Python</span>
                                <span style={{ fontSize: 10.5, color: 'var(--brand-lavender)', background: 'rgba(201,184,255,.12)', borderRadius: 999, padding: '3px 9px' }}>server-side &middot; your evidence</span>
                            </div>
                            <div style={{ padding: 16, fontFamily: mono, fontSize: 12.5, lineHeight: 1.7, background: 'var(--surface-sunken)' }}>
                                <div><span style={cmt}># runs in the platform, not the agent</span></div>
                                <div><span style={kw}>def</span> <span style={fn}>fetch_evidence</span>(task):</div>
                                <div style={{ paddingLeft: 18 }}>pr <span style={op}>=</span> github.pull_request(task.branch)</div>
                                <div style={{ paddingLeft: 18 }}>cov <span style={op}>=</span> coverage.for_sha(pr.head_sha)</div>
                                <div style={{ paddingLeft: 18 }}><span style={kw}>return</span> {'{'}<span style={str}>"pr"</span>: pr, <span style={str}>"coverage"</span>: cov{'}'}</div>
                                <div>&nbsp;</div>
                                <div><span style={kw}>def</span> <span style={fn}>validate</span>(task, evidence, user):</div>
                                <div style={{ paddingLeft: 18 }}><span style={kw}>return</span> evidence.coverage.pct <span style={op}>&gt;=</span> <span style={num}>0.85</span></div>
                            </div>
                        </div>
                    </div>
                </div>
            </section>

            {/* Customization */}
            <section style={{ borderTop: '1px solid var(--border-subtle)', background: '#0c0f14' }}>
                <div style={{ maxWidth: 1120, margin: '0 auto', padding: '96px 32px 92px' }}>
                    <div style={{ maxWidth: 640, marginBottom: 46 }}>
                        <SectionKicker dot="var(--brand-teal)" label="Make it yours" />
                        <h2 style={{ margin: 0, fontSize: 'clamp(28px,3.4vw,40px)', fontWeight: 600, letterSpacing: '-0.025em', lineHeight: 1.12, color: 'var(--text-primary)' }}>Customization that scales with the team.</h2>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(290px,1fr))', gap: 20 }}>
                        {[{
                            dot: 'var(--brand-lavender)', title: 'Per-column, per-project',
                            desc: "Attach a different gate to each transition, and override rules per project. The same board can be strict where it matters and light where it doesn't.",
                        }, {
                            dot: 'var(--brand-teal)', title: 'Start from templates',
                            desc: 'Pre-built execution and verification workflows get a project running in minutes — then you edit the rules instead of writing them from scratch.',
                        }, {
                            dot: '#a78bfa', title: 'Visual node builder',
                            desc: 'Every rule renders as an editable flowchart, so non-technical owners can read and adjust the logic without touching code.',
                        }].map((c) => (
                            <div key={c.title} style={{ background: 'var(--surface-card)', border: '1px solid var(--border-subtle)', borderRadius: 14, padding: 26 }}>
                                <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: c.dot, marginBottom: 16 }} />
                                <h3 style={{ margin: '0 0 9px', fontSize: 16.5, fontWeight: 600, letterSpacing: '-0.01em', color: 'var(--text-primary)' }}>{c.title}</h3>
                                <p style={{ margin: 0, fontSize: 14, lineHeight: 1.6, color: 'var(--text-secondary)' }}>{c.desc}</p>
                            </div>
                        ))}
                    </div>
                </div>
            </section>

            {/* CTA */}
            <section style={{ borderTop: '1px solid var(--border-subtle)', background: 'var(--surface-base)' }}>
                <div style={{ maxWidth: 1120, margin: '0 auto', padding: '84px 32px 90px', textAlign: 'center' }}>
                    <h2 style={{ margin: '0 auto 16px', fontSize: 'clamp(26px,3.2vw,38px)', fontWeight: 600, letterSpacing: '-0.025em', lineHeight: 1.1, color: 'var(--text-primary)', maxWidth: '22ch' }}>Powerful enough for your hardest rule. Safe by default.</h2>
                    <p style={{ margin: '0 auto 30px', fontSize: 16.5, lineHeight: 1.6, color: 'var(--text-secondary)', maxWidth: '52ch' }}>Set up your first Smart Gate in plain English &mdash; and reach for Starlark or Python the day you need them.</p>
                    <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: 13 }}>
                        <Link to={ROUTES.SIGNUP} style={{ fontSize: 15, fontWeight: 600, color: 'var(--surface-base)', background: 'var(--brand-lavender)', border: '1px solid var(--brand-lavender)', borderRadius: 9, padding: '13px 26px', textDecoration: 'none' }}>Start free</Link>
                        <Link to={ROUTES.WELCOME} style={{ fontSize: 15, fontWeight: 500, color: 'var(--text-primary)', background: 'transparent', border: '1px solid var(--border-active)', borderRadius: 9, padding: '13px 22px', textDecoration: 'none' }}>&larr; Back to overview</Link>
                    </div>
                </div>
            </section>
        </div>
    );
}
