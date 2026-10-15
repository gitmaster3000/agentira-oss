import { useEffect, useRef } from 'react';

// Interval poll that skips ticks while the tab is hidden. Pass the cadence the
// data needs (5 s while a run is active, 30 s otherwise); a new cadence
// restarts the timer. `fn` may change every render without restarting it.
export function useVisiblePoll(fn, ms, key) {
    const latest = useRef(fn);
    latest.current = fn;
    useEffect(() => {
        const id = setInterval(() => {
            if (document.visibilityState === 'visible') latest.current();
        }, ms);
        return () => clearInterval(id);
    }, [ms, key]);
}
