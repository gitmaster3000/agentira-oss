// Task templates — preset task content (description, priority, tags) plus a
// Definition-of-Done checklist a user can apply when creating a task. Mirrors
// the backend "professionalization" defaults so a single task can be held to
// the same engineering bar (logging, tests, Bruno integration tests, manual
// test docs, security, docs). Applying a template fills empty fields and
// merges its DoD — it never clobbers what the user already typed.

export const TASK_TEMPLATES = [
    {
        id: 'professionalization',
        name: 'Professionalization (full DoD)',
        priority: 'high',
        tags: ['professionalization'],
        description:
            'Bring this work to production grade: structured logging with levels, '
            + 'unit tests, live integration tests (Bruno), a manual test description '
            + 'for testers, security checks, and CI/CD via GitHub Actions. Tick every '
            + 'Definition of Done item before review.',
        dod: [
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
        priority: 'high',
        tags: ['bug'],
        description:
            'Reproduce the bug with a failing test first, then make it pass. '
            + 'Describe the root cause and the fix.',
        dod: [
            'Failing test reproduces the bug',
            'Fix verified — test passes',
            'No regressions in related tests',
        ],
    },
];

export function getTaskTemplate(id) {
    return TASK_TEMPLATES.find(t => t.id === id) || null;
}
