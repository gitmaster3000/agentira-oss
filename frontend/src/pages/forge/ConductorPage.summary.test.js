import { describe, it, expect } from 'vitest';
import { planSummary } from './ConductorPage';

describe('planSummary', () => {
    it('summarises per-project results honestly', () => {
        const p = { projects: [
            { project_id: 'a', ok: true, turn_id: 't1' },
            { project_id: 'b', undelivered: "Conductor's runtime is offline" },
            { project_id: 'c', skipped: 'nothing to plan' },
        ] };
        expect(planSummary(p)).toBe('3 project(s): 1 sent, 1 undelivered, 1 skipped');
    });
    it('keeps the old shapes', () => {
        expect(planSummary(null)).toBe('not run yet');
        expect(planSummary({ skipped: 'conductor_disabled' })).toBe('skipped — conductor_disabled');
    });
});
