import { useSyncExternalStore } from 'react';

// Pages publish their breadcrumb path (via <Breadcrumbs>); the top bar renders it.
// Stored as a JSON string so identical paths keep identity and don't re-render.
let current = '[]';
const listeners = new Set();

export function setCrumbs(items) {
    const next = JSON.stringify(items || []);
    if (next === current) return;
    current = next;
    listeners.forEach((l) => l());
}

const subscribe = (l) => { listeners.add(l); return () => listeners.delete(l); };
export const getSnapshot = () => current;

export function useCrumbs() {
    return JSON.parse(useSyncExternalStore(subscribe, getSnapshot));
}
