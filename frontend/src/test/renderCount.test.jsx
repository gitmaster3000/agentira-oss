import React, { useState } from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { renderCount } from './renderCount';

// Good: draft lives in the input component; the page only hears about it on submit.
function Composer({ onSubmit }) {
    const [draft, setDraft] = useState('');
    return (
        <input
            aria-label="comment"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && onSubmit(draft)}
        />
    );
}

// Bad: draft lifted into the page root.
function LiftedComposer({ draft, setDraft }) {
    return <input aria-label="comment" value={draft} onChange={(e) => setDraft(e.target.value)} />;
}

function GoodPage({ rc }) {
    return <div><rc.Probe id="page" /><rc.Profile id="composer"><Composer onSubmit={() => {}} /></rc.Profile></div>;
}

function BadPage({ rc }) {
    const [draft, setDraft] = useState('');
    return <div><rc.Probe id="page" /><rc.Profile id="composer"><LiftedComposer draft={draft} setDraft={setDraft} /></rc.Profile></div>;
}

const type = (text) => {
    const input = screen.getByLabelText('comment');
    let value = '';
    for (const ch of text) { value += ch; fireEvent.change(input, { target: { value } }); }
};

describe('renderCount', () => {
    it('typing N characters renders the composer at most N times and the page 0 times', () => {
        const rc = renderCount();
        render(<GoodPage rc={rc} />);
        rc.reset();
        type('hello');
        expect(rc.count('composer')).toBeLessThanOrEqual(5);
        expect(rc.count('page')).toBe(0);
    });

    it('detects a page that re-renders on every keystroke', () => {
        const rc = renderCount();
        render(<BadPage rc={rc} />);
        rc.reset();
        type('hello');
        expect(rc.count('page')).toBe(5);
    });
});
