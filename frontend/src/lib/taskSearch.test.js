import { describe, it, expect } from 'vitest';
import { matchesTaskSearch } from './taskSearch';

const task = { key: 'AP-123', title: 'Fix login' };

describe('matchesTaskSearch', () => {
    it('matches empty query', () => expect(matchesTaskSearch(task, '')).toBe(true));
    it('matches title', () => expect(matchesTaskSearch(task, 'LOGIN')).toBe(true));
    it('matches key case-insensitively', () => expect(matchesTaskSearch(task, 'ap-123')).toBe(true));
    it('matches partial key', () => expect(matchesTaskSearch(task, '123')).toBe(true));
    it('rejects non-match', () => expect(matchesTaskSearch(task, 'ap-999')).toBe(false));
    it('tolerates missing key', () => expect(matchesTaskSearch({ title: 'x' }, 'ap-1')).toBe(false));
});
