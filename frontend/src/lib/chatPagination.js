// Shared windowed-pagination helpers for the chat surfaces — the FloatingChat
// "quick chat" dock and the AgentDetail ChatTab "agent chat". Both keep a
// sliding window of messages: the live tail is refreshed by the poll, and
// older pages are fetched on demand as the user scrolls up. These pure helpers
// own the merge/sort/offset logic so it's identical on both surfaces and
// unit-tested in isolation.

// Chronological comparator. Missing timestamps sort oldest (treated as 0) so
// optimistic local cards without a created_at don't get stranded.
export function byCreatedAt(a, b) {
    const ta = a.created_at ? new Date(a.created_at).getTime() : 0;
    const tb = b.created_at ? new Date(b.created_at).getTime() : 0;
    return ta - tb;
}

// Number of server-persisted rows currently in the window (excludes optimistic
// `local-*` cards). This is the offset for the next older page — the backend
// pages backward from newest, so offset = how many real rows we already hold.
export function serverLoadedCount(messages) {
    return (messages || []).filter((m) => !String(m.id).startsWith('local-')).length;
}

// Merge a fetched page into the current window: dedupe server rows by id
// (incoming wins, so edits / finalized rows refresh), keep local-only cards
// (optimistic sends, /context output) until a real row supersedes them, and
// re-sort chronologically.
export function mergeWindow(prev, incoming) {
    const byId = new Map();
    for (const m of (prev || [])) {
        if (!String(m.id).startsWith('local-')) byId.set(m.id, m);
    }
    for (const m of (incoming || [])) byId.set(m.id, m);
    const locals = (prev || []).filter((m) => String(m.id).startsWith('local-'));
    return [...byId.values(), ...locals].sort(byCreatedAt);
}
