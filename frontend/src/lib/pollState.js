// Poll results are fresh objects every time, so `setState(result)` re-renders
// even when nothing changed. Return the previous value when the cheap key
// matches and React bails out of the update.

// Activity rows are append-only (nothing edits or deletes them), so same
// length + same first and last id means same list, whichever way it is sorted.
export function keepSameActivity(prev, next) {
    if (!Array.isArray(prev) || !Array.isArray(next)) return next;
    if (prev.length !== next.length) return next;
    const same = prev[0]?.id === next[0]?.id
        && prev[prev.length - 1]?.id === next[next.length - 1]?.id;
    return same ? prev : next;
}

// Small payloads (a task's runs): compare by value.
export function keepSameJson(prev, next) {
    return JSON.stringify(prev) === JSON.stringify(next) ? prev : next;
}
