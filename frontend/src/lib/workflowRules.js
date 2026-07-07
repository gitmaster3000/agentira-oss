// Renders the project's existing workflow config (templates/workflow/default.yaml,
// interpreted by backend/forge/workflow.py) as the two-method Starlark shape
// from the Workflow Engine plan (v4 §2, §11): on_enter (PROCESS) +
// validate_transition (GATE). No Starlark runtime exists yet (plan Phase 1) —
// this is a read-only renderer of the CURRENT config, not a live rule source.

// Mirrors backend/gates.py _TRANSITION_GATES. All gates today read task
// fields only (Phase 2 evidence.* providers haven't landed), so every
// condition is "asserted" — never "verified" — until evidence.* exists.
const GATE_CHECKS = {
    'backlog->todo': [
        { id: 'has_dod', source: 'task', expr: 'task.has_dod', reason: 'Definition of Done required before todo' },
        { id: 'has_assignee', source: 'task', expr: 'task.assignee', reason: 'assignee required' },
    ],
    'todo->in_progress': [
        { id: 'has_assignee', source: 'task', expr: 'task.assignee', reason: 'assignee required' },
    ],
    'in_progress->review': [
        { id: 'dod_all_checked', source: 'task', expr: 'task.dod_all_checked', reason: 'all DoD items must be checked' },
        { id: 'has_branch_or_pr', source: 'task', expr: 'task.branch or task.pr_url', reason: 'open a PR or push a branch first' },
    ],
    'review->done': [
        { id: 'pr_url_set', source: 'task', expr: 'task.pr_url', reason: 'PR must be open' },
        { id: 'dod_all_checked', source: 'task', expr: 'task.dod_all_checked', reason: 'all DoD items must be checked' },
    ],
};

/** Process steps a column's on_enter fires: assign / dispatch / notify. */
export function processSteps(columnName, flow) {
    const column = flow?.columns?.find((c) => c.name === columnName);
    if (!column) return [];
    const steps = [];
    if (column.on_enter?.dispatch_role) {
        const role = column.on_enter.dispatch_role;
        steps.push({ kind: 'assign', label: `assign role: ${role}`, role });
        steps.push({ kind: 'dispatch', label: `dispatch run: ${role}` });
    }
    // on_success on THIS column fires assign/dispatch on the task as it
    // ARRIVES in the next column — surfaced here as "on exit" so the canvas
    // reads as one continuous PROCESS zone for the column the user selected.
    const onSuccess = column.on_success;
    if (onSuccess?.assign_role) {
        steps.push({ kind: 'assign', label: `on advance: assign role ${onSuccess.assign_role}`, role: onSuccess.assign_role });
    }
    if (onSuccess?.dispatch) {
        steps.push({ kind: 'dispatch', label: `on advance: dispatch run` });
    }
    if (onSuccess?.integrate) {
        // Deterministic daemon-side action (not a rule intent) — the Starlark
        // renderer notes it as a comment, never a fabricated task.notify() call.
        steps.push({
            kind: 'notify',
            label: `merge to ${onSuccess.integrate.target_branch}${onSuccess.integrate.push ? ' + push' : ''}`,
            commentOnly: true,
        });
    }
    return steps;
}

/** Gate conditions guarding the column's exit transition, with asserted/verified badges. */
export function gateConditions(columnName, flow) {
    const column = flow?.columns?.find((c) => c.name === columnName);
    const to = column?.on_success?.advance_to;
    if (!to) return { to: null, conditions: [] };
    const conditions = GATE_CHECKS[`${columnName}->${to}`] || [];
    return { to, conditions };
}

/** Read-only Starlark rendering of the column's on_enter + validate_transition. */
export function renderStarlark(columnName, flow) {
    const steps = processSteps(columnName, flow);
    const { to, conditions } = gateConditions(columnName, flow);

    const lines = [`# ${columnName}.star  (generated preview — rendered from the existing workflow config)`];

    lines.push('', 'def on_enter(task, board):');
    if (steps.length === 0) {
        lines.push('    pass');
    } else {
        for (const step of steps) {
            if (step.commentOnly) lines.push(`    # ${step.label}`);
            else if (step.kind === 'assign') lines.push(`    task.assign(role="${step.role}")`);
            else if (step.kind === 'dispatch') lines.push('    task.dispatch_run()');
            else lines.push(`    task.notify()  # ${step.label}`);
        }
    }

    lines.push('', `def validate_transition(task, evidence, user):   # ${columnName} -> ${to || '(terminal)'}`);
    if (!to) {
        lines.push('    pass  # terminal column — no outbound transition');
    } else if (conditions.length === 0) {
        lines.push('    return True, ""');
    } else {
        for (const c of conditions) {
            lines.push(`    if not (${c.expr}):`);
            lines.push(`        return False, "${c.reason}"`);
        }
        lines.push('    return True, ""');
    }

    return lines.join('\n');
}
