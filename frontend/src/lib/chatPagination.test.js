import { describe, it, expect } from 'vitest';
import { byCreatedAt, serverLoadedCount, mergeWindow } from './chatPagination';

const at = (s) => `2026-06-07T00:00:${String(s).padStart(2, '0')}.000Z`;

describe('byCreatedAt', () => {
    it('orders by created_at ascending', () => {
        const out = [{ created_at: at(3) }, { created_at: at(1) }, { created_at: at(2) }]
            .sort(byCreatedAt);
        expect(out.map((m) => m.created_at)).toEqual([at(1), at(2), at(3)]);
    });

    it('treats a missing created_at as oldest', () => {
        const out = [{ id: 'b', created_at: at(2) }, { id: 'a' }].sort(byCreatedAt);
        expect(out.map((m) => m.id)).toEqual(['a', 'b']);
    });
});

describe('serverLoadedCount', () => {
    it('counts only server-persisted rows, ignoring optimistic local cards', () => {
        const win = [
            { id: 's1' }, { id: 'local-user-1' }, { id: 's2' }, { id: 'local-context-9' },
        ];
        expect(serverLoadedCount(win)).toBe(2);
    });

    it('is 0 for an empty / undefined window', () => {
        expect(serverLoadedCount([])).toBe(0);
        expect(serverLoadedCount(undefined)).toBe(0);
    });
});

describe('mergeWindow', () => {
    it('appends a newer tail page and keeps chronological order', () => {
        const prev = [{ id: 's1', created_at: at(1) }, { id: 's2', created_at: at(2) }];
        const incoming = [{ id: 's3', created_at: at(3) }];
        expect(mergeWindow(prev, incoming).map((m) => m.id)).toEqual(['s1', 's2', 's3']);
    });

    it('prepends an older page without dropping the existing window', () => {
        const prev = [{ id: 's3', created_at: at(3) }, { id: 's4', created_at: at(4) }];
        const older = [{ id: 's1', created_at: at(1) }, { id: 's2', created_at: at(2) }];
        expect(mergeWindow(prev, older).map((m) => m.id)).toEqual(['s1', 's2', 's3', 's4']);
    });

    it('dedupes by id with the incoming row winning (finalized content refresh)', () => {
        const prev = [{ id: 's1', created_at: at(1), content: 'draft' }];
        const incoming = [{ id: 's1', created_at: at(1), content: 'final' }];
        const out = mergeWindow(prev, incoming);
        expect(out).toHaveLength(1);
        expect(out[0].content).toBe('final');
    });

    it('keeps optimistic local cards until a real row supersedes them', () => {
        const prev = [
            { id: 's1', created_at: at(1) },
            { id: 'local-user-7', created_at: at(2) },
        ];
        // Poll returns the persisted version of that user turn as a real row.
        const incoming = [{ id: 's2', created_at: at(2) }];
        const out = mergeWindow(prev, incoming);
        // Both the local card and the new server row survive the merge; server
        // rows lead and local cards trail on an equal timestamp. The caller
        // drops the local card explicitly once its real id is known.
        expect(out.map((m) => m.id)).toEqual(['s1', 's2', 'local-user-7']);
    });

    it('handles null/undefined inputs without throwing', () => {
        expect(mergeWindow(undefined, undefined)).toEqual([]);
        expect(mergeWindow(null, [{ id: 's1', created_at: at(1) }]).map((m) => m.id))
            .toEqual(['s1']);
    });
});
