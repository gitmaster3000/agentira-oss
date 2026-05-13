const API_BASE = import.meta.env.VITE_API_URL || '/api';

function getToken() {
    return localStorage.getItem('agentira_token') || '';
}

export async function request(endpoint, options = {}) {
    const token = getToken();
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers,
    };
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const res = await fetch(`${API_BASE}${endpoint}`, {
        ...options,
        headers,
    });

    if (res.status === 401) {
        // Token expired or invalid — force re-login
        localStorage.removeItem('agentira_token');
        localStorage.removeItem('agentira_user');
        window.location.href = '/login';
        throw new Error('Session expired');
    }

    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        console.error(`API Error on ${endpoint}:`, err);
        throw new Error(err.detail || err.message || `API request failed (${res.status})`);
    }

    return res.json();
}

export const api = {
    // Service Accounts
    createServiceAccount: (name) => request('/service-accounts', { method: 'POST', body: JSON.stringify({ name }) }),
    listServiceAccounts: () => request('/service-accounts'),
    getServiceAccount: (id) => request(`/service-accounts/${id}`),
    deleteServiceAccount: (id) => request(`/service-accounts/${id}`, { method: 'DELETE' }),

    async login(username, password) {
        const res = await fetch(`${API_BASE}/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        if (!res.ok) throw new Error('Invalid credentials');
        const data = await res.json();
        if (data.token) localStorage.setItem('agentira_token', data.token);
        return data;
    },

    async signup(data) {
        const result = await request('/signup', { method: 'POST', body: JSON.stringify(data) });
        if (result.token) localStorage.setItem('agentira_token', result.token);
        return result;
    },

    async googleAuth(idToken) {
        const result = await request('/auth/google', { method: 'POST', body: JSON.stringify({ id_token: idToken }) });
        if (result.token) localStorage.setItem('agentira_token', result.token);
        return result;
    },

    async githubAuth(code) {
        const result = await request('/auth/github', { method: 'POST', body: JSON.stringify({ code }) });
        if (result.token) localStorage.setItem('agentira_token', result.token);
        return result;
    },

    async getAuthConfig() {
        return request('/auth/config');
    },

    // Projects — no more actor params, JWT handles identity
    getProjects: () => request('/projects'),
    createProject: (data) => request('/projects', { method: 'POST', body: JSON.stringify(data) }),
    getProject: (id) => request(`/projects/${id}`),
    updateProject: (id, data) => request(`/projects/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
    deleteProject: (id) => request(`/projects/${id}`, { method: 'DELETE' }),

    // Members
    getProjectMembers: (projectId) => request(`/projects/${projectId}/members`),
    addProjectMember: (projectId, profileName) => request(`/projects/${projectId}/members`, {
        method: 'POST',
        body: JSON.stringify({ profile_name: profileName })
    }),
    removeProjectMember: (projectId, profileName) => request(`/projects/${projectId}/members/${profileName}`, { method: 'DELETE' }),
    getProjectActivity: (projectId, limit = 50) => request(`/projects/${projectId}/activity?limit=${limit}`),

    // Board
    getBoard: (projectId) => request(`/projects/${projectId}/board`),
    getRoadmap: (projectId, groupBy = 'epic') => request(`/projects/${projectId}/roadmap?group_by=${groupBy}`),

    // Epics
    getEpics: (projectId) => request(projectId ? `/epics/?project_id=${projectId}` : '/epics/'),
    getEpic: (id) => request(`/epics/${id}`),
    createEpic: (projectId, data) => request(`/projects/${projectId}/epics`, { method: 'POST', body: JSON.stringify(data) }),
    updateEpic: (id, data) => request(`/epics/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
    deleteEpic: (id) => request(`/epics/${id}`, { method: 'DELETE' }),
    getEpicTasks: (id) => request(`/epics/${id}/tasks`),

    // Tasks
    listTasks: (projectId, status, assignee, priority) => {
        const params = new URLSearchParams();
        if (projectId) params.set('project_id', projectId);
        if (status) params.set('status', status);
        if (assignee) params.set('assignee', assignee);
        if (priority) params.set('priority', priority);
        return request(`/tasks?${params.toString()}`);
    },
    createTask: (data) => request('/tasks', { method: 'POST', body: JSON.stringify(data) }),
    getTask: (id) => request(`/tasks/${id}`),
    updateTask: (id, data) => request(`/tasks/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
    deleteTask: (id) => request(`/tasks/${id}`, { method: 'DELETE' }),
    moveTask: (taskId, status) => request(`/tasks/${taskId}/move`, { method: 'POST', body: JSON.stringify({ status }) }),
    addComment: (taskId, data) => request(`/tasks/${taskId}/comment`, { method: 'POST', body: JSON.stringify(data) }),
    getActivity: (taskId) => request(`/tasks/${taskId}/activity`),
    getChanges: (taskId, since) => request(`/tasks/${taskId}/changes?since=${encodeURIComponent(since)}`),

    // Workflow / Permissions
    getRoles: () => request('/workflow/rules').then(res => res.roles),
    getPermissions: () => request('/permissions'),
    createPermission: (data) => request('/permissions', {
        method: 'POST',
        body: JSON.stringify(data)
    }),
    createRole: (data) => request('/roles', {
        method: 'POST',
        body: JSON.stringify(data)
    }),
    grantPermission: (roleName, codename) => request('/permissions/grant', {
        method: 'POST',
        body: JSON.stringify({ role_name: roleName, codename })
    }),
    revokePermission: (roleName, codename) => request('/permissions/revoke', {
        method: 'POST',
        body: JSON.stringify({ role_name: roleName, codename })
    }),

    // Profiles
    getMe: () => request('/profiles/me'),
    getProfiles: (role) => request(`/profiles${role ? `?role=${role}` : ''}`),
    createProfile: (data) => request('/profiles', { method: 'POST', body: JSON.stringify(data) }),
    updateProfile: (id, data) => request(`/profiles/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
    deleteProfile: (id) => request(`/profiles/${id}`, { method: 'DELETE' }),

    // Attachments
    listAttachments: (taskId) => request(`/tasks/${taskId}/attachments`),
    uploadAttachment: (taskId, file) => {
        const formData = new FormData();
        formData.append('file', file);
        const token = getToken();
        const headers = {};
        if (token) headers['Authorization'] = `Bearer ${token}`;
        return fetch(`${API_BASE}/tasks/${taskId}/attachments`, {
            method: 'POST',
            body: formData,
            headers,
        }).then(res => {
            if (!res.ok) throw new Error(`Upload failed (${res.status})`);
            return res.json();
        });
    },
    deleteAttachment: (id) => request(`/attachments/${id}`, { method: 'DELETE' }),
    getAttachmentDownloadUrl: (id) => `${API_BASE}/attachments/${id}/download`,

    // Roadmap
    // getRoadmap already defined above

    // Git Integration
    listTaskCommits: (taskId) => request(`/tasks/${taskId}/commits`),
    linkCommit: (taskId, data) => request(`/tasks/${taskId}/commits`, { method: 'POST', body: JSON.stringify(data) }),
    linkPR: (taskId, data) => request(`/tasks/${taskId}/prs`, { method: 'POST', body: JSON.stringify(data) }),
    suggestBranch: (taskId) => request(`/tasks/${taskId}/suggest-branch`),

    // Notifications
    getNotifications: (unreadOnly = true) => request(`/notifications?unread_only=${unreadOnly}`),
    markNotificationRead: (id) => request(`/notifications/${id}/read`, { method: 'PATCH' }),

    // Generic
    request,

    // Forge
    forge: {
        getStats: () => request('/forge/stats'),
        listAgents: (status) => request(`/forge/agents${status ? `?status=${status}` : ''}`),
        getAgent: (id) => request(`/forge/agents/${id}`),
        createAgent: (data) => request('/forge/agents', { method: 'POST', body: JSON.stringify(data) }),
        updateAgent: (id, data) => request(`/forge/agents/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
        deleteAgent: (id) => request(`/forge/agents/${id}`, { method: 'DELETE' }),
        heartbeat: (id, status = 'online') => request(`/forge/agents/${id}/heartbeat`, { method: 'POST', body: JSON.stringify({ status }) }),
        listRuns: (params = {}) => {
            const qs = new URLSearchParams();
            for (const [k, v] of Object.entries(params)) {
                if (v !== undefined && v !== '') qs.set(k, v);
            }
            const q = qs.toString();
            return request(`/forge/runs${q ? '?' + q : ''}`);
        },
        getRun: (id) => request(`/forge/runs/${id}`),
        createRun: (data) => request('/forge/runs', { method: 'POST', body: JSON.stringify(data) }),
        startRun: (id) => request(`/forge/runs/${id}/start`, { method: 'POST' }),
        cancelRun: (id) => request(`/forge/runs/${id}/cancel`, { method: 'POST' }),
        pauseRun: (id) => request(`/forge/runs/${id}/pause`, { method: 'POST' }),
        resumeRun: (id) => request(`/forge/runs/${id}/resume`, { method: 'POST' }),
        completeRun: (id, data) => request(`/forge/runs/${id}/complete`, { method: 'POST', body: JSON.stringify(data) }),
        updateRunStatus: (id, data) => request(`/forge/runs/${id}/status`, { method: 'POST', body: JSON.stringify(data) }),
        listRunEvents: (runId) => request(`/forge/runs/${runId}/events`),
        getTriggerEvent: (runId) => request(`/forge/runs/${runId}/trigger-event`),

        // Task ↔ Forge bridge
        scheduleTaskRun: (taskId, agentId) =>
            request(`/forge/tasks/${taskId}/run`, {
                method: 'POST',
                body: JSON.stringify({ agent_id: agentId }),
            }),
        listTaskRuns: (taskId) => request(`/forge/tasks/${taskId}/runs`),

        // Events
        listEvents: (params = {}) => {
            const qs = new URLSearchParams();
            for (const [k, v] of Object.entries(params)) {
                if (v !== undefined && v !== '' && v !== null) qs.set(k, v);
            }
            const q = qs.toString();
            return request(`/forge/events${q ? '?' + q : ''}`);
        },
        getEvent: (id) => request(`/forge/events/${id}`),
        createEvent: (data) => request('/forge/events', { method: 'POST', body: JSON.stringify(data) }),
        markEventProcessed: (id) => request(`/forge/events/${id}/process`, { method: 'POST' }),
        listDeliveries: (eventId) => request(`/forge/events/${eventId}/deliveries`),
        createDelivery: (data) => request('/forge/deliveries', { method: 'POST', body: JSON.stringify(data) }),
        updateDeliveryStatus: (id, data) => request(`/forge/deliveries/${id}/status`, { method: 'POST', body: JSON.stringify(data) }),
        attachEventToRun: (data) => request('/forge/run-events', { method: 'POST', body: JSON.stringify(data) }),

        // Messages (chat)
        listMessages: (agentId, params = {}) => {
            const qs = new URLSearchParams();
            for (const [k, v] of Object.entries(params)) {
                if (v !== undefined && v !== '') qs.set(k, v);
            }
            const q = qs.toString();
            return request(`/forge/agents/${agentId}/messages${q ? '?' + q : ''}`);
        },
        createMessage: (agentId, data) => request(`/forge/agents/${agentId}/messages`, { method: 'POST', body: JSON.stringify(data) }),

        // Webhook logs
        listWebhookLogs: (agentId, params = {}) => {
            const qs = new URLSearchParams();
            for (const [k, v] of Object.entries(params)) {
                if (v !== undefined && v !== '') qs.set(k, v);
            }
            const q = qs.toString();
            return request(`/forge/agents/${agentId}/webhook-logs${q ? '?' + q : ''}`);
        },

        // Schedule
        updateSchedule: (agentId, data) => request(`/forge/agents/${agentId}/schedule`, { method: 'PUT', body: JSON.stringify(data) }),

        // Costs
        getAgentCosts: (agentId) => request(`/forge/agents/${agentId}/costs`),
        estimateCost: (data) => request('/forge/cost-estimate', { method: 'POST', body: JSON.stringify(data) }),
        getRuntimeCosts: (agentId) => request(`/forge/agents/${agentId}/runtime/costs`),
        getPricing: () => request('/forge/pricing'),

        // OpenClaw integration
        getRuntimeStatus: (agentId) => request(`/forge/agents/${agentId}/runtime/status`),
        sendRuntimeChat: (agentId, data) => request(`/forge/agents/${agentId}/runtime/chat`, { method: 'POST', body: JSON.stringify(data) }),
        getOpenClawOverview: () => request('/forge/openclaw/overview'),
        syncOpenClaw: () => request('/forge/openclaw/sync', { method: 'POST' }),
        getOpenClawModels: () => request('/forge/openclaw/models'),
        setOpenClawAgentModel: (agentName, model) => request('/forge/openclaw/agent-model', { method: 'POST', body: JSON.stringify({ agent_name: agentName, model }) }),
        resetAgentStatus: (agentId) => request(`/forge/agents/${agentId}/reset-status`, { method: 'POST' }),
        listRuntimes: (params) => {
            const q = new URLSearchParams(params || {}).toString();
            return request(`/forge/runtimes${q ? '?' + q : ''}`);
        },
        getRuntime: (id) => request(`/forge/runtimes/${id}`),
        listAgentProjects: (agentId) => request(`/forge/agents/${agentId}/projects`),
        getDispatchPreview: (agentId, projectId) => request(
            `/forge/agents/${agentId}/dispatch-preview${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''}`
        ),
    },
};
