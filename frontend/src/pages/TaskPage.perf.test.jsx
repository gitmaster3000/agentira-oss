import React, { Profiler } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

// Counts how many times the markdown renderer is asked to render.
const counts = vi.hoisted(() => ({ markdown: 0, sections: 0 }));
vi.mock('react-markdown', () => ({
    default: ({ children }) => { counts.markdown += 1; return <div>{children}</div>; },
}));
vi.mock('remark-gfm', () => ({ default: () => {} }));
// One CollapsibleSection renders per plan-tab section, so this counts plan-tab re-renders.
vi.mock('../components/TaskDetail/CollapsibleSection', () => ({
    CollapsibleSection: ({ children }) => { counts.sections += 1; return <div>{children}</div>; },
}));

const BIG = 'Lorem **ipsum** dolor sit amet, consectetur adipiscing elit. '.repeat(90).slice(0, 5000);
const task = {
    id: 'T1', key: 'AP-1', project_id: 'P1', title: 'Perf task', description: BIG, status: 'todo',
    priority: 'medium', assignee: '', tags: [], dod_items: [], created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z', repos: [],
};
const activities = Array.from({ length: 60 }, (_, i) => ({
    id: `a${i}`, actor: 'ali', action: i % 2 ? 'commented' : 'moved', detail: `entry ${i}`,
    created_at: '2026-01-01T00:00:00Z',
}));
const members = [{ id: 'm1', name: 'ali', display_name: 'Ali', role: 'admin', account_type: 'human' }];

const calls = vi.hoisted(() => []);
vi.mock('../api', () => {
    const overrides = {
        getTask: () => Promise.resolve(structuredClone(task)),
        getProjectMembers: () => Promise.resolve(structuredClone(members)),
        getActivity: () => Promise.resolve(structuredClone(activities)),
        getEpics: () => Promise.resolve([]),
        listTaskCommits: () => Promise.resolve([]),
        listProjectRepos: () => Promise.resolve([]),
        forge: { listTaskRuns: () => Promise.resolve([]) },
    };
    const api = new Proxy(overrides, {
        get: (t, k) => (k in t ? (...a) => { calls.push(String(k)); return t[k](...a); }
            : () => Promise.resolve([])),
    });
    return { api };
});
vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ user: { display_name: 'Ali' } }) }));

import { TaskPage } from './TaskPage';

const commits = { n: 0, ms: 0 };
const onRender = (_id, _phase, actual) => { commits.n += 1; commits.ms += actual; };

async function mountPage() {
    render(
        <Profiler id="page" onRender={onRender}>
            <MemoryRouter initialEntries={['/studio/tasks/AP-1']}>
                <Routes><Route path="/studio/tasks/:taskId" element={<TaskPage />} /></Routes>
            </MemoryRouter>
        </Profiler>,
    );
    await screen.findByText('Perf task');
    await act(async () => { await new Promise(r => setTimeout(r, 20)); });
}

// Types `n` characters one by one, returns per-keystroke render cost.
function typeInto(el, n = 30, base = '') {
    commits.n = 0; commits.ms = 0; counts.markdown = 0; counts.sections = 0;
    const t0 = performance.now();
    for (let i = 1; i <= n; i++) fireEvent.change(el, { target: { value: base + 'x'.repeat(i) } });
    const wall = performance.now() - t0;
    return {
        commitsPerKey: commits.n / n,
        renderMsPerKey: +(commits.ms / n).toFixed(2),
        wallMsPerKey: +(wall / n).toFixed(2),
        markdownRendersPerKey: counts.markdown / n,
        sectionRendersPerKey: counts.sections / n,
    };
}

describe('TaskPage typing cost (5k-char description, 60 activity rows)', () => {
    beforeEach(() => { calls.length = 0; });
    afterEach(() => vi.useRealTimers());

    it('comment keystrokes do not re-render the page', async () => {
        await mountPage();
        const box = screen.getByPlaceholderText(/Add a comment/);
        const r = typeInto(box);
        console.log('PERF comment', JSON.stringify(r));
        expect(r.markdownRendersPerKey).toBe(0);
        expect(r.sectionRendersPerKey).toBe(0);
    });

    it('title and description edit keystrokes do not re-render the page', async () => {
        await mountPage();
        fireEvent.click(screen.getByTitle('Edit task'));
        const title = screen.getByLabelText('Title');
        const rt = typeInto(title);
        console.log('PERF title', JSON.stringify(rt));
        const desc = screen.getByLabelText('Description');
        const rd = typeInto(desc, 30, BIG);
        console.log('PERF description', JSON.stringify(rd));
        expect(rt.sectionRendersPerKey).toBe(0);
        expect(rd.sectionRendersPerKey).toBe(0);
        expect(rd.markdownRendersPerKey).toBe(0);
    });

    it('a poll that returns identical data does not re-render', async () => {
        vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
        await mountPage();
        commits.n = 0;
        await act(async () => { vi.advanceTimersByTime(9000); await new Promise(r => setTimeout(r, 30)); });
        console.log('PERF poll commits over 9s (3 activity polls)', commits.n);
        expect(commits.n).toBe(0);
    });
});
