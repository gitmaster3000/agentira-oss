import React, { Profiler } from 'react';

/**
 * Render counter for tests of the rules in docs-oss/docs/technical/frontend-performance.md.
 *
 *   const rc = renderCount();
 *   render(<Page rc={rc} />);   // Page renders <rc.Probe id="page" /> and wraps Composer in <rc.Profile id="composer">
 *   rc.reset();
 *   await user.type(input, 'hello');
 *   expect(rc.count('composer')).toBeLessThanOrEqual(5);
 *   expect(rc.count('page')).toBe(0);
 *
 * Profile counts commits of its subtree (the component under test and its children).
 * Probe counts its own renders: create it inline in the JSX of the component that must
 * NOT re-render (a test harness, or a mocked wrapper). It re-renders only when that parent
 * does. Never pass a pre-built <rc.Probe/> element in as a prop: React skips an unchanged
 * element, so it would never count.
 */
export function renderCount() {
    const counts = {};
    const bump = (id) => { counts[id] = (counts[id] || 0) + 1; };

    function Profile({ id, children }) {
        return <Profiler id={id} onRender={() => bump(id)}>{children}</Profiler>;
    }

    function Probe({ id }) {
        bump(id);
        return null;
    }

    return {
        Profile,
        Probe,
        count: (id) => counts[id] || 0,
        reset: () => { for (const k of Object.keys(counts)) counts[k] = 0; },
    };
}
