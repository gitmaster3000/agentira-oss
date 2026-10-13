import { describe, it, expect, vi } from 'vitest';
import { parseGitAddress, fetchRepoInfo } from './gitAddress';

describe('parseGitAddress', () => {
    it.each([
        ['https://github.com/acme/web-app.git', 'github.com', 'acme', 'web-app'],
        ['https://github.com/acme/web-app/', 'github.com', 'acme', 'web-app'],
        ['git@github.com:acme/web-app.git', 'github.com', 'acme', 'web-app'],
        ['ssh://git@gitlab.com/group/sub/api', 'gitlab.com', 'sub', 'api'],
    ])('%s', (input, host, owner, name) => {
        expect(parseGitAddress(input)).toEqual({ host, owner, name });
    });

    it('rejects things that are not a repo address', () => {
        expect(parseGitAddress('')).toBeNull();
        expect(parseGitAddress('hello')).toBeNull();
        expect(parseGitAddress('https://github.com/acme')).toBeNull();
    });
});

describe('fetchRepoInfo', () => {
    const gh = { host: 'github.com', owner: 'a', name: 'b' };

    it('returns branch, language and visibility for a GitHub repo', async () => {
        const f = vi.fn().mockResolvedValue({ ok: true, json: async () => ({
            default_branch: 'trunk', language: 'Python', description: 'd', private: false }) });
        expect(await fetchRepoInfo(gh, f)).toEqual({
            defaultBranch: 'trunk', language: 'Python', description: 'd', isPrivate: false });
        expect(f).toHaveBeenCalledWith('https://api.github.com/repos/a/b');
    });

    it('returns null for private/missing repos, other hosts and network errors', async () => {
        expect(await fetchRepoInfo(gh, vi.fn().mockResolvedValue({ ok: false }))).toBeNull();
        expect(await fetchRepoInfo(gh, vi.fn().mockRejectedValue(new Error('x')))).toBeNull();
        const f = vi.fn();
        expect(await fetchRepoInfo({ ...gh, host: 'gitlab.com' }, f)).toBeNull();
        expect(f).not.toHaveBeenCalled();
    });
});
