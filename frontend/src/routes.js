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
    STUDIO_SETTINGS: '/studio/settings',
    STUDIO_TASK: (taskId) => `/studio/tasks/${taskId}`,
    STUDIO_EPIC: (epicId) => `/studio/epics/${epicId}`,

    // Forge
    FORGE: '/forge',
    FORGE_AGENTS: '/forge/agents',
    FORGE_AGENT: (agentId) => `/forge/agents/${agentId}`,
    FORGE_RUNS: '/forge/runs',
    FORGE_RUN: (runId) => `/forge/runs/${runId}`,
};
