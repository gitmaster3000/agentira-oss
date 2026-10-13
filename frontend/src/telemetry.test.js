import { describe, it, expect } from 'vitest';
import { normalizePath } from './telemetry';

describe('normalizePath', () => {
    it('collapses ids, task keys and tokens so routes group together', () => {
        expect(normalizePath('/studio/project/db0e2fd7fc1d/board')).toBe('/studio/project/:id/board');
        expect(normalizePath('/tasks/EE-1')).toBe('/tasks/:key');
        expect(normalizePath('/invites/wD63a0kaejgjI-J7aIehD4o_ofmaS81h/accept')).toBe('/invites/:token/accept');
        expect(normalizePath('/notifications?unread_only=false')).toBe('/notifications');
    });
});
