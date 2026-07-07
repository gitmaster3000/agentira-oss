import React from 'react';
import { gateConditions } from '../../lib/workflowRules';

// Board overview for the Workflow Engine — the sequence of columns with the
// gate that guards each hand-off shown at a glance. Per-column detail (process,
// gate checks, prompt) lives in the side panel, not here. Inline styles + SVG
// paths ported from the design's "Workflow Engine.dc.html" board zone; all
// content is real data from getBoard + getProjectWorkflow.

const DOT_RING = ['#768390', '#58a6ff', '#ff9800', '#38bdf8', '#2ecc71'];

const Gear = ({ s = 11 }) => (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="#00bcd4" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>
);

const Arrow = ({ s = 20, stroke = '#484f58' }) => (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 12h14M13 6l6 6-6 6" /></svg>
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
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '6px', marginBottom: '8px' }}>
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

/** The board overview: the whole pipeline as a sequence, each hand-off carrying
 *  the count of real gate conditions that guard it. Select a column to open its
 *  detail in the side panel. */
export function ColumnCanvas({ columnNames, tasksByColumn, selected, onSelect, flow, columnsUi }) {
    return (
        <div style={{ position: 'relative', minHeight: '100%', backgroundColor: '#0a0d14', backgroundImage: 'radial-gradient(#1a2333 1px, transparent 1px)', backgroundSize: '22px 22px', padding: '30px 26px' }}>
            <div style={{ position: 'relative', background: 'rgba(20,25,33,.55)', border: '1px solid #2a313c', borderRadius: '14px', padding: '20px 18px 16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', justifyContent: 'center', marginBottom: '16px' }}>
                    <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#c9b8ff' }} />
                    <span style={{ fontSize: '10px', letterSpacing: '.1em', textTransform: 'uppercase', color: '#aeb6c0', fontWeight: 600 }}>The board · every column has a process &amp; a gate</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'center', flexWrap: 'wrap', gap: 0, marginBottom: '6px' }}>
                    {columnNames.map((name, i) => {
                        const tasks = tasksByColumn[name] || [];
                        const badge = i < columnNames.length - 1 ? gateConditions(name, flow, columnsUi) : null;
                        return (
                            <React.Fragment key={name}>
                                <ColumnTile name={name} tasks={tasks} dotColor={DOT_RING[i % DOT_RING.length]} selected={selected === name} onSelect={onSelect} />
                                {badge && <GateBadge n={badge.to === columnNames[i + 1] ? badge.conditions.length : 0} />}
                            </React.Fragment>
                        );
                    })}
                </div>
                <div style={{ textAlign: 'center', marginTop: '4px' }}>
                    <span style={{ fontSize: '9.5px', color: '#768390' }}>Selecting the <span style={{ color: '#c9b8ff' }}>{selected}</span> column — its process, gate &amp; prompt are on the right</span>
                </div>
            </div>
        </div>
    );
}
