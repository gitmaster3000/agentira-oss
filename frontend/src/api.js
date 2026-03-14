const API_BASE = '/api';

function getActor() {
    const stored = localStorage.getItem('agentira_user');
    if (stored) {
        try {
            const user = JSON.parse(stored);
            return user.name || 'system';
        } catch (e) {
            return 'system';
        }
    }
    return 'system';
}

export async function request(endpoint, options = {}) {
    const res = await fetch(`${API_BASE}${endpoint}`, {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            ...options.headers,
        },
    });

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
        return res.json();
    },

    async signup(data) {
        return request('/signup', { method: 'POST', body: JSON.stringify(data) });
    },

    // Projects
    getProjects: () => request('/projects'),
    createProject: (data) => request('/projects', { method: 'POST', body: JSON.stringify({ actor: getActor(), ...data }) }),
    getProject: (id) => request(`/projects/${id}`),
    updateProject: (id, data) => request(`/projects/${id}`, { method: 'PATCH', body: JSON.stringify({ actor: getActor(), ...data }) }),
    deleteProject: (id) => request(`/projects/${id}`, { method: 'DELETE' }),

    // Members
    getProjectMembers: (projectId) => request(`/projects/${projectId}/members`),
    addProjectMember: (projectId, profileName, actor = null) => request(`/projects/${projectId}/members`, {
        method: 'POST',
        body: JSON.stringify({ profile_name: profileName, actor: actor || getActor() })
    }),
    removeProjectMember: (projectId, profileName) => request(`/projects/${projectId}/members/${profileName}`, { method: 'DELETE' }),

    // Board
    getBoard: (projectId) => request(`/board/${projectId}`),

    // Tasks
    createTask: (data) => request('/tasks', { method: 'POST', body: JSON.stringify({ actor: getActor(), ...data }) }),
    getTask: (id) => request(`/tasks/${id}`),
    updateTask: (id, data) => request(`/tasks/${id}`, { method: 'PATCH', body: JSON.stringify({ actor: getActor(), ...data }) }),
    deleteTask: (id) => request(`/tasks/${id}`, { method: 'DELETE' }),
    moveTask: (taskId, status, actor = null) => request(`/tasks/${taskId}/move`, { method: 'POST', body: JSON.stringify({ status, actor: actor || getActor() }) }),
    addComment: (taskId, data) => request(`/tasks/${taskId}/comment`, { method: 'POST', body: JSON.stringify({ actor: getActor(), ...data }) }),
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
    getMe: (name) => request(`/profiles/me?actor=${encodeURIComponent(name)}`),
    getProfiles: (role) => request(`/profiles${role ? `?role=${role}` : ''}`),
    createProfile: (data) => request('/profiles', { method: 'POST', body: JSON.stringify(data) }),
    updateProfile: (id, data) => request(`/profiles/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
    deleteProfile: (id) => request(`/profiles/${id}`, { method: 'DELETE' }),

    // Attachments
    listAttachments: (taskId) => request(`/tasks/${taskId}/attachments`),
    uploadAttachment: (taskId, file) => {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('uploaded_by', getActor());
        return fetch(`${API_BASE}/tasks/${taskId}/attachments`, {
            method: 'POST',
            body: formData,
        }).then(res => {
            if (!res.ok) throw new Error(`Upload failed (${res.status})`);
            return res.json();
        });
    },
    deleteAttachment: (id) => request(`/attachments/${id}`, { method: 'DELETE' }),
    getAttachmentDownloadUrl: (id) => `${API_BASE}/attachments/${id}/download`,

    // Git Integration
    listTaskCommits: (taskId) => request(`/tasks/${taskId}/commits`),
    linkCommit: (taskId, data) => request(`/tasks/${taskId}/commits`, { method: 'POST', body: JSON.stringify(data) }),
    linkPR: (taskId, data) => request(`/tasks/${taskId}/prs`, { method: 'POST', body: JSON.stringify(data) }),
    suggestBranch: (taskId) => request(`/tasks/${taskId}/suggest-branch`),

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
        completeRun: (id, data) => request(`/forge/runs/${id}/complete`, { method: 'POST', body: JSON.stringify(data) }),

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
        getPricing: () => request('/forge/pricing'),

        // OpenClaw integration
        getRuntimeStatus: (agentId) => request(`/forge/agents/${agentId}/runtime/status`),
        sendRuntimeChat: (agentId, data) => request(`/forge/agents/${agentId}/runtime/chat`, { method: 'POST', body: JSON.stringify(data) }),
        getOpenClawOverview: () => request('/forge/openclaw/overview'),
        syncOpenClaw: () => request('/forge/openclaw/sync', { method: 'POST' }),
    },
};
