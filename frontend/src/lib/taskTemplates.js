// Templates for the New Task modal. Two independent kinds:
//
//   TASK_TEMPLATES — prefill the task's own fields (description, priority,
//   tags). Applied as one-shot buttons; they never touch the DoD.
//
//   DOD_TEMPLATES — a named group of Definition-of-Done items. Toggled on/off:
//   applying adds the group's items (tagged with the template id), un-applying
//   removes exactly those items, so the active template is always visible.
//
// The Professionalization presets mirror the backend default backlog so a task
// can be held to the same engineering bar (logging, tests, Bruno integration
// tests, manual test docs, security, docs).

export const TASK_TEMPLATES = [
    {
        id: 'professionalization',
        name: 'Professionalization',
        priority: 'high',
        tags: ['professionalization'],
        description:
            'Bring this work to production grade: structured logging with levels, '
            + 'unit tests, live integration tests (Bruno), a manual test description '
            + 'for testers, security checks, and CI/CD via GitHub Actions.',
    },
    {
        id: 'bugfix',
        name: 'Bug fix',
        priority: 'high',
        tags: ['bug'],
        description:
            'Reproduce the bug with a failing test first, then make it pass. '
            + 'Describe the root cause and the fix.',
    },
];

export const DOD_TEMPLATES = [
    {
        id: 'professionalization',
        name: 'Professionalization',
        items: [
            'Technical documentation',
            'Unit tests',
            'Bruno integration tests',
            'Manual test description attached',
            'User documentation',
            'Security check',
        ],
    },
    {
        id: 'bugfix',
        name: 'Bug fix',
        items: [
            'Failing test reproduces the bug',
            'Fix verified — test passes',
            'No regressions in related tests',
        ],
    },
];

export function getTaskTemplate(id) {
    return TASK_TEMPLATES.find(t => t.id === id) || null;
}

export function getDodTemplate(id) {
    return DOD_TEMPLATES.find(t => t.id === id) || null;
}
