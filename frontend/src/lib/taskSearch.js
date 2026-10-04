// Search matches the task title or its key (e.g. "AP-123"), case-insensitive.
export function matchesTaskSearch(task, query) {
    const q = (query || '').trim().toLowerCase();
    if (!q) return true;
    return (task.title || '').toLowerCase().includes(q)
        || String(task.key || '').toLowerCase().includes(q);
}
