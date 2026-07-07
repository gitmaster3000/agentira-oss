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
        expect(gateConditions('done', FLOW)).toEqual({ to: null, conditions: [] });
    });

    it('returns the known task-field conditions for in_progress -> review', () => {
        const { to, conditions } = gateConditions('in_progress', FLOW);
        expect(to).toBe('review');
        expect(conditions.map((c) => c.id)).toEqual(['dod_all_checked', 'has_branch_or_pr']);
        // Today every gate reads task.* only — no evidence.* provider has landed.
        expect(conditions.every((c) => c.source === 'task')).toBe(true);
    });

    it('returns [] when the column has no advance_to', () => {
        expect(gateConditions('backlog', FLOW)).toEqual({ to: null, conditions: [] });
    });
});

describe('renderStarlark', () => {
    it('renders an on_enter/validate_transition pair for a column with both process and gate', () => {
        const src = renderStarlark('in_progress', FLOW);
        expect(src).toContain('def on_enter(task, board):');
        expect(src).toContain('def validate_transition(task, evidence, user):   # in_progress -> review');
        expect(src).toContain('if not (task.dod_all_checked):');
        expect(src).toContain('return False, "all DoD items must be checked"');
        expect(src).toContain('return True, ""');
    });

    it('renders a pass-only validate_transition for a terminal column', () => {
        const src = renderStarlark('done', FLOW);
        expect(src).toContain('# done -> (terminal)');
        expect(src).toContain('pass  # terminal column');
    });

    it('renders pass for a column with no on_enter steps', () => {
        const src = renderStarlark('backlog', FLOW);
        expect(src).toContain('def on_enter(task, board):\n    pass');
    });

    it('renders the bare role string for an on-advance assign, not the display label', () => {
        const src = renderStarlark('in_progress', FLOW);
        expect(src).toContain('task.assign(role="reviewer")');
        expect(src).not.toContain('assign role reviewer');
    });

    it('renders an integrate policy as a comment line, never a fabricated task.notify() call', () => {
        const src = renderStarlark('review', FLOW);
        expect(src).toContain('# merge to main + push');
        expect(src).not.toContain('task.notify()');
    });
});
