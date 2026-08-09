import { describe, it, expect } from 'vitest';
import { pickCurrentRun, summaryStamp } from './TaskPage';

describe('pickCurrentRun', () => {
    it('returns null for empty/invalid', () => {
        expect(pickCurrentRun([])).toBe(null);
        expect(pickCurrentRun(null)).toBe(null);
    });
    it('picks the newest run by created_at', () => {
        const runs = [
            { id: 'a', created_at: '2026-06-01T00:00:00Z' },
            { id: 'b', created_at: '2026-06-03T00:00:00Z' },
            { id: 'c', created_at: '2026-06-02T00:00:00Z' },
        ];
        expect(pickCurrentRun(runs).id).toBe('b');
    });
});

describe('summaryStamp', () => {
    const now = '2026-06-19T12:00:00Z';
    it('is null when no run or no summary', () => {
        expect(summaryStamp(null, null, null, now)).toBe(null);
        expect(summaryStamp(null, { summary: '' }, null, now)).toBe(null);
    });
    it('keeps prior stamp when summary unchanged', () => {
        const run = { summary: 'same', status: 'running' };
        expect(summaryStamp('same', run, 'OLD', now)).toBe('OLD');
    });
    it('stamps now when a running summary rolls', () => {
        const run = { summary: 'new', status: 'running' };
        expect(summaryStamp('old', run, 'OLD', now)).toBe(now);
    });
    it('uses run finished_at on first sight of a finished run', () => {
        const run = { summary: 'done', status: 'completed', finished_at: 'FIN' };
        expect(summaryStamp(null, run, null, now)).toBe('FIN');
    });
});
