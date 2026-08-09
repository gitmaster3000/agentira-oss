import React from 'react';
import { renderStarlark } from '../../lib/workflowRules';

// Code view of the Workflow Engine — a port of the design's "Code" canvas:
// filename pill + Starlark badge + line-numbered, read-only source generated
// from the current workflow config. Comment lines are dimmed for legibility.

function Line({ text }) {
    const isComment = text.trimStart().startsWith('#');
    return <div style={{ color: isComment ? 'var(--text-muted)' : 'var(--text-secondary)' }}>{text.length ? text : ' '}</div>;
}

/** Read-only Starlark preview of the selected column's rule (on_enter + gate). */
export function RuleCodePane({ columnName, flow, columnsUi }) {
    const lines = renderStarlark(columnName, flow, columnsUi).split('\n');
    return (
        <div style={{ background: 'var(--surface-sunken)', padding: '22px 24px', minHeight: '332px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px', flexWrap: 'wrap' }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '7px', fontFamily: 'ui-monospace,SFMono-Regular,Menlo,monospace', fontSize: '11px', color: 'var(--text-secondary)', background: 'var(--surface-nav)', border: '1px solid var(--border-default)', borderRadius: '6px', padding: '4px 10px' }}>
                    <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: 'var(--brand-lavender)' }} />{columnName}.star
                </span>
                <span style={{ fontSize: '10px', fontWeight: 600, letterSpacing: '.04em', color: 'var(--brand-teal)', background: 'rgba(128,203,196,.12)', border: '1px solid rgba(128,203,196,.3)', borderRadius: '5px', padding: '3px 8px' }}>Starlark</span>
                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>generated from the visual editor · read-only</span>
            </div>
            <div style={{ display: 'flex', fontFamily: 'ui-monospace,SFMono-Regular,Menlo,monospace', fontSize: '12.5px', lineHeight: 1.8 }}>
                <div style={{ textAlign: 'right', color: 'var(--border-strong)', paddingRight: '16px', borderRight: '1px solid var(--border-default)', userSelect: 'none' }}>
                    {lines.map((_, i) => <div key={i}>{i + 1}</div>)}
                </div>
                <div style={{ paddingLeft: '16px', whiteSpace: 'pre', overflowX: 'auto', flex: 1 }}>
                    {lines.map((text, i) => <Line key={i} text={text} />)}
                </div>
            </div>
        </div>
    );
}
