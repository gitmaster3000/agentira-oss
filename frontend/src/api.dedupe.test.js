import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { request } from './api';

const ok = (body) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });

describe('request() GET de-duplication', () => {
    beforeEach(() => { globalThis.fetch = vi.fn(() => ok({ items: [1, 2] })); });
    afterEach(() => { vi.restoreAllMocks(); });

    it('shares one network call between identical concurrent GETs', async () => {
        const [a, b] = await Promise.all([request('/projects/p1/board'), request('/projects/p1/board')]);
        expect(fetch).toHaveBeenCalledTimes(1);
        expect(a).toEqual(b);
    });

    it('gives each caller its own copy', async () => {
        const a = await request('/projects/p1/members');
        a.items.push(3);
        const b = await request('/projects/p1/members');
        expect(b.items).toEqual([1, 2]);
    });

    it('does not share different endpoints', async () => {
        await Promise.all([request('/a'), request('/b')]);
        expect(fetch).toHaveBeenCalledTimes(2);
    });

    it('a write clears reused GETs', async () => {
        await request('/projects/p1/board');
        await request('/tasks', { method: 'POST', body: '{}' });
        await request('/projects/p1/board');
        expect(fetch).toHaveBeenCalledTimes(3);
    });

    it('never reuses a failed GET', async () => {
        fetch.mockImplementationOnce(() => Promise.reject(new Error('offline')));
        await expect(request('/x')).rejects.toThrow('offline');
        await expect(request('/x')).resolves.toEqual({ items: [1, 2] });
        expect(fetch).toHaveBeenCalledTimes(2);
    });
});
