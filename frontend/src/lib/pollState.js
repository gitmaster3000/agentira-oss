// Poll results are fresh objects every time, so `setState(result)` re-renders
// even when nothing changed. Return the previous value when the cheap key
// matches and React bails out of the update.

// Activity is append-only: same length + same newest id means same list.
export function keepSameActivity(prev, next) {
    if (!Array.isArray(prev) || !Array.isArray(next)) return next;
    if (prev.length !== next.length) return next;
    return prev[prev.length - 1]?.id === next[next.length - 1]?.id ? prev : next;
}

// Small payloads (a task's runs): compare by value.
export function keepSameJson(prev, next) {
    return JSON.stringify(prev) === JSON.stringify(next) ? prev : next;
}
