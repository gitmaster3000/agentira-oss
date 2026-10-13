/**
 * Read a pasted git address and look up what we can about the repo, so
 * attaching one needs a single paste.
 */

// https://github.com/org/repo(.git)  |  git@github.com:org/repo.git  |  ssh://git@host/org/repo
export function parseGitAddress(input) {
    const raw = (input || '').trim();
    if (!raw) return null;
    let host; let path;
    const scp = raw.match(/^[\w.-]+@([^:\s/]+):(.+)$/);
    if (scp) {
        [, host, path] = scp;
    } else {
        try {
            const u = new URL(raw);
            if (!u.hostname) return null;
            host = u.hostname;
            path = u.pathname;
        } catch {
            return null;
        }
    }
    const parts = path.replace(/\.git$/i, '').split('/').filter(Boolean);
    if (parts.length < 2) return null;
    const [owner, name] = [parts[parts.length - 2], parts[parts.length - 1]];
    return { host: host.toLowerCase(), owner, name };
}

// Only GitHub exposes this without credentials. Anything else (or a private
// repo) resolves to null: the caller keeps the parsed name and moves on.
export async function fetchRepoInfo(parsed, fetchImpl = fetch) {
    if (!parsed || parsed.host !== 'github.com') return null;
    try {
        const res = await fetchImpl(`https://api.github.com/repos/${parsed.owner}/${parsed.name}`);
        if (!res.ok) return null;
        const d = await res.json();
        return {
            defaultBranch: d.default_branch || '',
            language: d.language || '',
            description: d.description || '',
            isPrivate: !!d.private,
        };
    } catch {
        return null;
    }
}
