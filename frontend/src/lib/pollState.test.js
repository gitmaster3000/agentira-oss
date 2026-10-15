import { describe, it, expect } from 'vitest';
import { keepSameActivity, keepSameJson } from './pollState';

describe('keepSameActivity', () => {
    it('keeps the previous list when length and newest id match', () => {
        const prev = [{ id: 'a' }, { id: 'b' }];
        expect(keepSameActivity(prev, [{ id: 'a' }, { id: 'b' }])).toBe(prev);
    });
    it('takes the new list when an entry was appended', () => {
        const next = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];
        expect(keepSameActivity([{ id: 'a' }, { id: 'b' }], next)).toBe(next);
    });
    it('takes the new list when the first id differs (newest-first order)', () => {
        const next = [{ id: 'x' }, { id: 'b' }];
        expect(keepSameActivity([{ id: 'a' }, { id: 'b' }], next)).toBe(next);
    });
    it('takes the new list when the newest id differs', () => {
        const next = [{ id: 'a' }, { id: 'x' }];
        expect(keepSameActivity([{ id: 'a' }, { id: 'b' }], next)).toBe(next);
    });
});

describe('keepSameJson', () => {
    it('keeps identity for equal payloads and swaps for changed ones', () => {
        const prev = { id: 1, status: 'running' };
        expect(keepSameJson(prev, { id: 1, status: 'running' })).toBe(prev);
        const next = { id: 1, status: 'done' };
        expect(keepSameJson(prev, next)).toBe(next);
    });
});
