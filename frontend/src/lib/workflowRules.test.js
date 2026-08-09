import { describe, it, expect } from 'vitest';
import { processSteps, gateConditions, renderStarlark } from './workflowRules';

const FLOW = {
    columns: [
        { name: 'backlog' },
        { name: 'todo' },
        {
            name: 'in_progress',
            on_success: { advance_to: 'review', assign_role: 'reviewer', dispatch: true },
        },
        {
            name: 'review',
            on_success: {
                advance_to: 'done', assign_role: null, dispatch: false,
                integrate: { target_branch: 'main', push: true },
            },
        },
        { name: 'done', on_enter: { dispatch_role: 'documentation' } },
    ],
};

// Real gate checks as the backend's columns_ui payload delivers them.
const COLUMNS_UI = {
    in_progress: {
        advance_to: 'review',
        gates: [
            { name: 'dod_all_checked', description: 'Every Definition-of-Done item is checked.' },
            { name: 'has_branch_or_pr', description: 'Task has a branch or a PR URL.' },
        ],
    },
    review: { advance_to: 'done', gates: [] },
    done: { advance_to: null, gates: [] },
    backlog: { advance_to: null, gates: [] },
};

describe('processSteps', () => {
    it('returns nothing for a column with no on_enter/on_success actions', () => {
        expect(processSteps('backlog', FLOW)).toEqual([]);
    });

    it('surfaces on_enter dispatch_role as assign + dispatch, carrying the role on the step', () => {
        const steps = processSteps('done', FLOW);
        expect(steps).toEqual([
            { kind: 'assign', label: 'assign role: documentation', role: 'documentation' },
            { kind: 'dispatch', label: 'dispatch run: documentation' },
        ]);
    });

    it('surfaces on_success assign_role + dispatch + integrate, carrying the role on the step', () => {
        const steps = processSteps('in_progress', FLOW);
        expect(steps).toContainEqual({ kind: 'assign', label: 'on advance: assign role reviewer', role: 'reviewer' });
        expect(steps).toContainEqual({ kind: 'dispatch', label: 'on advance: dispatch run' });
    });

    it('surfaces an integrate policy on the terminal-bound column, marked comment-only', () => {
        const steps = processSteps('review', FLOW);
        const integrate = steps.find((s) => s.kind === 'notify' && s.label.includes('main'));
        expect(integrate).toBeTruthy();
        expect(integrate.commentOnly).toBe(true);
    });

    it('returns [] for a column absent from the flow', () => {
        expect(processSteps('nonexistent', FLOW)).toEqual([]);
    });
});

describe('gateConditions', () => {
    it('has no outbound gate for a terminal column', () => {
        expect(gateConditions('done', FLOW, COLUMNS_UI)).toEqual({ to: null, conditions: [] });
    });

    it('returns the real backend gate checks for in_progress -> review', () => {
        const { to, conditions } = gateConditions('in_progress', FLOW, COLUMNS_UI);
        expect(to).toBe('review');
        expect(conditions.map((c) => c.id)).toEqual(['dod_all_checked', 'has_branch_or_pr']);
        // The reason text is the backend's own gate description, not a UI copy.
        expect(conditions[0].reason).toBe('Every Definition-of-Done item is checked.');
    });

    it('returns [] when the column has no advance_to', () => {
        expect(gateConditions('backlog', FLOW, COLUMNS_UI)).toEqual({ to: null, conditions: [] });
    });
});

describe('renderStarlark', () => {
    it('renders an on_enter/validate_transition pair for a column with both process and gate', () => {
        const src = renderStarlark('in_progress', FLOW, COLUMNS_UI);
        expect(src).toContain('def on_enter(task, board):');
        expect(src).toContain('def validate_transition(task, evidence, user):   # in_progress -> review');
        expect(src).toContain('if not (task.dod_all_checked):');
        expect(src).toContain('return False, "Every Definition-of-Done item is checked."');
        expect(src).toContain('return True, ""');
    });

    it('renders a pass-only validate_transition for a terminal column', () => {
        const src = renderStarlark('done', FLOW, COLUMNS_UI);
        expect(src).toContain('# done -> (terminal)');
        expect(src).toContain('pass  # terminal column');
    });

    it('renders pass for a column with no on_enter steps', () => {
        const src = renderStarlark('backlog', FLOW, COLUMNS_UI);
        expect(src).toContain('def on_enter(task, board):\n    pass');
    });

    it('renders the bare role string for an on-advance assign, not the display label', () => {
        const src = renderStarlark('in_progress', FLOW, COLUMNS_UI);
        expect(src).toContain('task.assign(role="reviewer")');
        expect(src).not.toContain('assign role reviewer');
    });

    it('renders an integrate policy as a comment line, never a fabricated task.notify() call', () => {
        const src = renderStarlark('review', FLOW, COLUMNS_UI);
        expect(src).toContain('# merge to main + push');
        expect(src).not.toContain('task.notify()');
    });
});
