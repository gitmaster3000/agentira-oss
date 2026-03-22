// ── Route Constants ─────────────────────────────────────────────────
// Single source of truth for all app routes.

export const ROUTES = {
    // Public
    WELCOME: '/welcome',
    LOGIN: '/login',
    SIGNUP: '/signup',
    GITHUB_CALLBACK: '/auth/github/callback',

    // Studio
    STUDIO: '/studio',
    STUDIO_BOARD: (projectId) => `/studio/board/${projectId}`,
    STUDIO_PROJECT: (projectId) => `/studio/project/${projectId}`,
    STUDIO_PROJECT_BOARD: (projectId) => `/studio/project/${projectId}/board`,
    STUDIO_PROJECT_BACKLOG: (projectId) => `/studio/project/${projectId}/backlog`,
    STUDIO_PROJECT_ROADMAP: (projectId) => `/studio/project/${projectId}/roadmap`,
    STUDIO_SETTINGS: '/studio/settings',
    STUDIO_TASK: (taskId) => `/studio/tasks/${taskId}`,
};
