// Reactive store for the "active" Studio project id. Detail routes
// (/studio/tasks/:taskId, /studio/epics/:epicId) carry no projectId URL
// param, so Navbar + Sidebar would otherwise lose the selected project.
// ProjectLayout / TaskPage / EpicPage push the id here; Navbar + Sidebar
// read it as a fallback when the URL has none.
import { useSyncExternalStore } from 'react';

const KEY = 'agentira:studio:lastProjectId';

let current = null;
try { current = localStorage.getItem(KEY); } catch {}

const listeners = new Set();

export function setCurrentProjectId(id) {
    if (!id || id === current) return;
    current = id;
    try { localStorage.setItem(KEY, id); } catch {}
    listeners.forEach((l) => l());
}

function subscribe(cb) {
    listeners.add(cb);
    return () => listeners.delete(cb);
}

export function useCurrentProjectId() {
    return useSyncExternalStore(subscribe, () => current);
}
