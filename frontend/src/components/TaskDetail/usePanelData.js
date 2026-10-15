import { useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../../api';
import { keepSameActivity, keepSameJson } from '../../lib/pollState';
import { useVisiblePoll } from '../../lib/useVisiblePoll';
import { LIVE_RUN_STATUSES } from './PanelRuns';

// Everything the side panel loads for one task. Activity and runs refresh on
// the shared poll rule: 5 s only while a run is live, 30 s otherwise, never
// while the tab is hidden; unchanged results keep their identity.
export function usePanelData(taskId) {
    const [activities, setActivities] = useState([]);
    const [attachments, setAttachments] = useState([]);
    const [commits, setCommits] = useState([]);
    const [taskRuns, setTaskRuns] = useState([]);

    const loadTaskRuns = useCallback(async () => {
        try {
            const data = await api.forge.listTaskRuns(taskId);
            if (Array.isArray(data)) setTaskRuns(prev => keepSameJson(prev, data));
        } catch { /* forge may be down */ }
    }, [taskId]);
    const loadActivity = useCallback(async () => {
        try {
            const data = await api.getActivity(taskId);
            setActivities(prev => keepSameActivity(prev, data));
        } catch (err) { console.error(err); }
    }, [taskId]);
    const loadAttachments = useCallback(async () => {
        try {
            const data = await api.listAttachments(taskId);
            if (Array.isArray(data)) setAttachments(data);
        } catch { /* ignore */ }
    }, [taskId]);
    const loadCommits = useCallback(async () => {
        try {
            const data = await api.listTaskCommits(taskId);
            if (Array.isArray(data)) setCommits(data);
        } catch { /* ignore */ }
    }, [taskId]);

    useEffect(() => {
        loadActivity();
        loadAttachments();
        loadCommits();
        loadTaskRuns();
    }, [loadActivity, loadAttachments, loadCommits, loadTaskRuns]);

    const live = taskRuns.some(r => LIVE_RUN_STATUSES.includes(r.status));
    useVisiblePoll(() => { loadActivity(); loadTaskRuns(); }, live ? 5000 : 30000, taskId);

    return { activities, attachments, commits, taskRuns, loadActivity, loadAttachments, loadTaskRuns };
}

// Panel width: user-draggable, remembered across sessions.
const WIDTH_KEY = 'taskPanelWidth';
const MIN_WIDTH = 320;
const MAX_WIDTH = 900;
const DEFAULT_WIDTH = 384;
const clampWidth = (w) => Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.round(w)));

export function usePanelWidth() {
    const [width, setWidth] = useState(() => {
        const saved = Number(localStorage.getItem(WIDTH_KEY));
        return saved ? clampWidth(saved) : DEFAULT_WIDTH;
    });
    const widthRef = useRef(width);
    widthRef.current = width;

    // Drag the left divider to widen/narrow the panel. Dragging left (smaller
    // clientX) grows it, since the panel is anchored to the right edge.
    const startResize = (e) => {
        e.preventDefault();
        const startX = e.clientX;
        const startWidth = widthRef.current;
        const onMove = (ev) => setWidth(clampWidth(startWidth + (startX - ev.clientX)));
        const onUp = () => {
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
            localStorage.setItem(WIDTH_KEY, String(widthRef.current));
        };
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
    };
    return { width, startResize };
}
