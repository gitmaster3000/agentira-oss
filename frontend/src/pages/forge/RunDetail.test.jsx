import { describe, it, expect } from 'vitest';
import { previewEvents } from './RunDetail';

describe('previewEvents', () => {
    it('returns empty for null/empty', () => {
        expect(previewEvents(null)).toEqual({ shown: [], hiddenCount: 0 });
        expect(previewEvents([])).toEqual({ shown: [], hiddenCount: 0 });
    });

    it('shows all when under the limit, nothing hidden', () => {
        const evts = [{ id: 1 }, { id: 2 }, { id: 3 }];
        const { shown, hiddenCount } = previewEvents(evts, 8);
        expect(shown).toEqual(evts);
        expect(hiddenCount).toBe(0);
    });

    it('shows all when exactly at the limit', () => {
        const evts = Array.from({ length: 8 }, (_, i) => ({ id: i }));
        const { shown, hiddenCount } = previewEvents(evts, 8);
        expect(shown).toHaveLength(8);
        expect(hiddenCount).toBe(0);
    });

    it('keeps the most recent tail and counts the rest as hidden', () => {
        const evts = Array.from({ length: 12 }, (_, i) => ({ id: i }));
        const { shown, hiddenCount } = previewEvents(evts, 8);
        expect(shown).toHaveLength(8);
        // tail = ids 4..11
        expect(shown[0].id).toBe(4);
        expect(shown[7].id).toBe(11);
        expect(hiddenCount).toBe(4);
    });

    it('uses the default limit when none is passed', () => {
        const evts = Array.from({ length: 10 }, (_, i) => ({ id: i }));
        const { shown, hiddenCount } = previewEvents(evts);
        expect(shown).toHaveLength(8);
        expect(hiddenCount).toBe(2);
    });
});
