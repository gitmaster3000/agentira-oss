import React, { Profiler, useState } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// Render-cost checks for the side panel and the Create Task modal (AP-696).
// Counts requests on open, markdown re-parses and section re-renders per keystroke.
const counts = vi.hoisted(() => ({ markdown: 0, sections: 0, calls: [] }));
vi.mock('react-markdown', () => ({
    default: ({ children }) => { counts.markdown += 1; return <div>{children}</div>; },
}));
vi.mock('remark-gfm', () => ({ default: () => {} }));
vi.mock('./TaskDetail/CollapsibleSection', () => ({
    CollapsibleSection: ({ children }) => { counts.sections += 1; return <div>{children}</div>; },
}));

const BIG = 'Lorem **ipsum** dolor sit amet, consectetur adipiscing elit. '.repeat(90).slice(0, 5000);
const task = {
    id: 'T1', key: 'AP-1', project_id: 'P1', title: 'Perf task', description: BIG, status: 'todo',
    priority: 'medium', assignee: '', tags: [], dod_items: [], repos: [],
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
};
const activities = Array.from({ length: 60 }, (_, i) => ({
    id: `a${i}`, actor: 'ali', action: i % 2 ? 'commented' : 'moved', detail: `entry ${i}`,
    created_at: '2026-01-01T00:00:00Z',
}));
const members = [{ id: 'm1', name: 'ali', display_name: 'Ali', role: 'admin', account_type: 'human' }];
const epics = [{ id: 'E1', title: 'Epic one' }];
const projectTasks = Array.from({ length: 600 }, (_, i) => ({
    id: `t${i}`, key: `AP-${i}`, title: `Task ${i}`, description: BIG, tags: [`tag${i % 40}`, 'perf'],
}));

vi.mock('../api', () => {
    const impl = {
        getActivity: () => Promise.resolve(structuredClone(activities)),
        getProjectMembers: () => Promise.resolve(structuredClone(members)),
        getEpics: () => Promise.resolve(structuredClone(epics)),
        getProject: () => Promise.resolve({ id: 'P1', name: 'Acme' }),
        listTasks: () => Promise.resolve(structuredClone(projectTasks)),
        forge: { listTaskRuns: () => Promise.resolve([]) },
    };
    const api = new Proxy(impl, {
        get: (t, k) => (k in t
            ? (typeof t[k] === 'function' ? (...a) => { counts.calls.push(String(k)); return t[k](...a); } : t[k])
            : () => Promise.resolve([])),
    });
    return { api };
});
vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ user: { display_name: 'Ali' } }) }));
// CreateTaskModal calls useNavigate once per render, so this counts its renders.
const nav = vi.hoisted(() => ({ renders: 0 }));
vi.mock('react-router-dom', async (orig) => ({
    ...(await orig()),
    useNavigate: () => { nav.renders += 1; return () => {}; },
}));

import { TaskDetailPanel } from './TaskDetailPanel';
import { CreateTaskModal } from './CreateTaskModal';

const commits = { n: 0, ms: 0 };
const onRender = (_id, _phase, actual) => { commits.n += 1; commits.ms += actual; };
const flush = () => act(async () => { await new Promise(r => setTimeout(r, 30)); });

function Panel() {
    const [isEditing, setIsEditing] = useState(false);
    return (
        <Profiler id="p" onRender={onRender}>
            <MemoryRouter>
                <TaskDetailPanel task={task} members={members} epics={epics} isEditing={isEditing}
                    setIsEditing={setIsEditing} onClose={() => {}} onUpdate={() => {}} onSelectTask={() => {}} />
            </MemoryRouter>
        </Profiler>
    );
}

function typeInto(el, n = 30, base = '') {
    commits.n = 0; commits.ms = 0; counts.markdown = 0; counts.sections = 0; nav.renders = 0;
    const t0 = performance.now();
    for (let i = 1; i <= n; i++) fireEvent.change(el, { target: { value: base + 'x'.repeat(i) } });
    const wall = performance.now() - t0;
    return {
        renderMsPerKey: +(commits.ms / n).toFixed(2),
        wallMsPerKey: +(wall / n).toFixed(2),
        markdownPerKey: counts.markdown / n,
        sectionsPerKey: counts.sections / n,
        modalRendersPerKey: nav.renders / n,
    };
}

describe('side panel typing cost (5k-char description, 60 activity rows)', () => {
    beforeEach(() => { counts.calls.length = 0; });
    afterEach(() => vi.useRealTimers());

    it('comment keystrokes do not re-render the panel body', async () => {
        render(<Panel />);
        await screen.findByText('Perf task');
        await flush();
        const r = typeInto(screen.getByPlaceholderText(/Comment or @mention/));
        console.log('PERF panel comment', JSON.stringify(r));
        expect(r.markdownPerKey).toBe(0);
        expect(r.sectionsPerKey).toBe(0);
    });

    it('title and description edit keystrokes do not re-render the panel body', async () => {
        render(<Panel />);
        await screen.findByText('Perf task');
        await flush();
        fireEvent.click(screen.getByTitle('Edit'));
        const rt = typeInto(screen.getByDisplayValue('Perf task'));
        console.log('PERF panel title', JSON.stringify(rt));
        const rd = typeInto(screen.getByDisplayValue(BIG), 30, BIG);
        console.log('PERF panel description', JSON.stringify(rd));
        expect(rt.sectionsPerKey).toBe(0);
        expect(rd.sectionsPerKey).toBe(0);
    });

    it('unchanged polls do not re-render', async () => {
        vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
        render(<Panel />);
        await screen.findByText('Perf task');
        await flush();
        commits.n = 0; counts.sections = 0;
        const before = counts.calls.filter(k => k === 'getActivity').length;
        // Idle task: 30 s cadence, so 90 s is 3 polls.
        await act(async () => { vi.advanceTimersByTime(90000); await new Promise(r => setTimeout(r, 40)); });
        const polls = counts.calls.filter(k => k === 'getActivity').length - before;
        console.log('PERF panel poll commits over 3 polls', commits.n, 'section renders', counts.sections);
        expect(polls).toBe(3);
        expect(commits.n).toBe(0);
        expect(counts.sections).toBe(0);
    });
});

describe('Create Task modal', () => {
    beforeEach(() => { counts.calls.length = 0; });

    function Modal() {
        return (
            <Profiler id="m" onRender={onRender}>
                <MemoryRouter>
                    <CreateTaskModal projectId="P1" members={members} epics={epics} projectName="Acme"
                        onClose={() => {}} onCreated={() => {}} />
                </MemoryRouter>
            </Profiler>
        );
    }

    it('opens with options filled and no request', async () => {
        render(<Modal />);
        // First frame, before any effect or promise settles.
        const assignee = screen.getByLabelText('Assignee');
        const epic = screen.getByLabelText('Epic');
        const optionsOnFirstFrame = { assignee: assignee.options.length, epic: epic.options.length };
        await flush();
        console.log('PERF modal first-frame options', JSON.stringify(optionsOnFirstFrame),
            'requests on open', counts.calls.length, JSON.stringify(counts.calls));
        expect(optionsOnFirstFrame).toEqual({ assignee: 2, epic: 2 });
        expect(counts.calls).toEqual([]);
    });

    it('title and description keystrokes stay cheap', async () => {
        render(<Modal />);
        await flush();
        const rt = typeInto(screen.getByLabelText('Title'));
        const rd = typeInto(screen.getByLabelText('Description'));
        console.log('PERF modal title (task list not loaded)', JSON.stringify(rt));
        console.log('PERF modal description (task list not loaded)', JSON.stringify(rd));
        fireEvent.focus(screen.getByLabelText('Tags'));
        await flush();
        const rl = typeInto(screen.getByLabelText('Title'));
        console.log('PERF modal title (600 tasks loaded)', JSON.stringify(rl));
        // Typing never re-renders the modal itself, with or without the task list loaded.
        for (const r of [rt, rd, rl]) {
            expect(r.modalRendersPerKey).toBe(0);
            expect(r.renderMsPerKey).toBeLessThan(50);
        }
    });
});
