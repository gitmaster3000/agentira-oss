import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useVisiblePoll } from './useVisiblePoll';

const setVisibility = (v) => Object.defineProperty(document, 'visibilityState', { value: v, configurable: true });

describe('useVisiblePoll', () => {
    beforeEach(() => { vi.useFakeTimers(); setVisibility('visible'); });
    afterEach(() => { vi.useRealTimers(); setVisibility('visible'); });

    it('ticks at the given cadence', () => {
        const fn = vi.fn();
        renderHook(() => useVisiblePoll(fn, 30000));
        vi.advanceTimersByTime(29999);
        expect(fn).not.toHaveBeenCalled();
        vi.advanceTimersByTime(1);
        expect(fn).toHaveBeenCalledTimes(1);
    });

    it('skips ticks while the tab is hidden', () => {
        const fn = vi.fn();
        renderHook(() => useVisiblePoll(fn, 1000));
        setVisibility('hidden');
        vi.advanceTimersByTime(5000);
        expect(fn).not.toHaveBeenCalled();
        setVisibility('visible');
        vi.advanceTimersByTime(1000);
        expect(fn).toHaveBeenCalledTimes(1);
    });

    it('switches cadence when it changes and calls the latest fn', () => {
        const a = vi.fn(); const b = vi.fn();
        const { rerender } = renderHook(({ fn, ms }) => useVisiblePoll(fn, ms), { initialProps: { fn: a, ms: 30000 } });
        rerender({ fn: b, ms: 5000 });
        vi.advanceTimersByTime(5000);
        expect(a).not.toHaveBeenCalled();
        expect(b).toHaveBeenCalledTimes(1);
    });
});
