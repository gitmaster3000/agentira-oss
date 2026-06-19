// Return types for this module are described in src/agentira.types.ts.
// Imported as JSDoc so plain JS callers get IDE typing without a TS build step.
/** @typedef {import('./agentira.types').Project} Project */
/** @typedef {import('./agentira.types').Task} Task */
/** @typedef {import('./agentira.types').Run} Run */
/** @typedef {import('./agentira.types').Notification} Notification */

const API_BASE = import.meta.env.VITE_API_URL || '/api';

function getToken() {
    return localStorage.getItem('agentira_token') || '';
}

// Turn any API error shape into a readable string. FastAPI 422s return
// `detail` as a LIST of {loc,msg,type} objects — stringifying that gave the
// dreaded "[object Object]". Handle string, list, and object detail shapes.
function extractError(err, status) {
    const d = err?.detail ?? err?.message;
    if (typeof d === 'string') return d;
    if (Array.isArray(d)) {
        return d.map(e => {
            const field = Array.isArray(e?.loc) ? e.loc[e.loc.length - 1] : '';
            return field ? `${field}: ${e.msg}` : (e?.msg || JSON.stringify(e));
        }).join('; ');
    }
    if (d && typeof d === 'object') return d.msg || JSON.stringify(d);
    return `Request failed (${status})`;
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
        throw new Error(extractError(err, res.status));
    }

    return res.json();
}

// Folder upload: send parallel files[] + paths[] (browser webkitRelativePath)
// to a /…/attachments/folder endpoint so structure is preserved server-side.
function uploadFolder(endpoint, files) {
    const formData = new FormData();
    for (const f of files) {
        formData.append('files', f);
        formData.append('paths', f.relativePath || f.webkitRelativePath || f.name);
    }
    const token = getToken();
    const headers = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    return fetch(`${API_BASE}${endpoint}`, { method: 'POST', body: formData, headers })
        .then(res => {
            if (!res.ok) throw new Error(`Upload failed (${res.status})`);
            return res.json();
        });
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

    // Invites — invite-only signup.
    getInvite: (code) => request(`/invites/${code}`),
    async acceptInvite(code, data) {
        const result = await request(`/invites/${code}/accept`, { method: 'POST', body: JSON.stringify(data) });
        if (result.token) localStorage.setItem('agentira_token', result.token);
        return result;
    },
    // Admin: create a member invite for the caller's org.
    createInvite: (email) => request('/invites', { method: 'POST', body: JSON.stringify(email ? { email } : {}) }),

    // Admin: approve a daemon browser-login (device code).
    approveCliLogin: (userCode) => request('/auth/cli/approve', { method: 'POST', body: JSON.stringify({ user_code: userCode }) }),

    async googleAuth(idToken, invite) {
        const result = await request('/auth/google', { method: 'POST', body: JSON.stringify({ id_token: idToken, invite: invite || null }) });
        if (result.token) localStorage.setItem('agentira_token', result.token);
        return result;
    },

    async githubAuth(code, invite) {
        const result = await request('/auth/github', { method: 'POST', body: JSON.stringify({ code, invite: invite || null }) });
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

    // AP-121: per-project repos
    listProjectRepos: (id) => request(`/projects/${id}/repos`),
    addProjectRepo: (id, data) => request(`/projects/${id}/repos`, {
        method: 'POST', body: JSON.stringify(data),
    }),
    removeProjectRepo: (id, name) => request(
        `/projects/${id}/repos/${encodeURIComponent(name)}`,
        { method: 'DELETE' },
    ),
    // AP-197: connect/update a repo's remote so the daemon clones it into its
    // own workspace instead of worktree-ing off a local (possibly TCC-blocked) path.
    updateProjectRepo: (id, name, data) => request(
        `/projects/${id}/repos/${encodeURIComponent(name)}`,
        { method: 'PATCH', body: JSON.stringify(data) },
    ),

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
    // The download route requires the bearer token, which a plain <a href>
    // can't carry — fetch with the header, then save the blob.
    downloadAttachment: async (id, filename) => {
        const token = getToken();
        const headers = {};
        if (token) headers['Authorization'] = `Bearer ${token}`;
        const res = await fetch(`${API_BASE}/attachments/${id}/download`, { headers });
        if (!res.ok) throw new Error(`Download failed (${res.status})`);
        const blobUrl = window.URL.createObjectURL(await res.blob());
        const a = document.createElement('a');
        a.href = blobUrl;
        a.download = filename || 'download';
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(blobUrl);
    },

    // AP-152: project-level attachments — same table, same download/delete
    // endpoints above, distinct list/upload routes.
    listProjectAttachments: (projectId) => request(`/projects/${projectId}/attachments`),
    uploadProjectAttachment: (projectId, file) => {
        const formData = new FormData();
        formData.append('file', file);
        const token = getToken();
        const headers = {};
        if (token) headers['Authorization'] = `Bearer ${token}`;
        return fetch(`${API_BASE}/projects/${projectId}/attachments`, {
            method: 'POST',
            body: formData,
            headers,
        }).then(res => {
            if (!res.ok) throw new Error(`Upload failed (${res.status})`);
            return res.json();
        });
    },
    // Folder upload (AP-278): preserves structure via webkitRelativePath.
    uploadProjectFolder: (projectId, files) =>
        uploadFolder(`/projects/${projectId}/attachments/folder`, files),
    uploadTaskFolder: (taskId, files) =>
        uploadFolder(`/tasks/${taskId}/attachments/folder`, files),

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
        // System Concierge agent — powers the floating chat.
        getConcierge: () => request('/forge/concierge'),
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
        retryRun: (id) => request(`/forge/runs/${id}/retry`, { method: 'POST' }),
        pauseRun: (id) => request(`/forge/runs/${id}/pause`, { method: 'POST' }),
        resumeRun: (id) => request(`/forge/runs/${id}/resume`, { method: 'POST' }),
        completeRun: (id, data) => request(`/forge/runs/${id}/complete`, { method: 'POST', body: JSON.stringify(data) }),
        updateRunStatus: (id, data) => request(`/forge/runs/${id}/status`, { method: 'POST', body: JSON.stringify(data) }),
        listRunEvents: (runId) => request(`/forge/runs/${runId}/events`),
        getTriggerEvent: (runId) => request(`/forge/runs/${runId}/trigger-event`),

        // Task ↔ Forge bridge
        // AP-112: prepare = create PENDING run with editable prompt, no dispatch.
        prepareTaskRun: (taskId, agentId) =>
            request(`/forge/tasks/${taskId}/prepare-run`, {
                method: 'POST',
                body: JSON.stringify({ agent_id: agentId }),
            }),
        // AP-112: dispatch the PENDING run, optionally with edited prompt.
        dispatchRun: (runId, prompt) =>
            request(`/forge/runs/${runId}/dispatch`, {
                method: 'POST',
                body: JSON.stringify(prompt != null ? { prompt } : {}),
            }),
        // AP-112: discard a never-dispatched PENDING run.
        discardRun: (runId) =>
            request(`/forge/runs/${runId}/discard`, { method: 'POST' }),
        // AP-113: pre-run checklist for a READY run.
        getRunReadyChecks: (runId) =>
            request(`/forge/runs/${runId}/ready-checks`),
        scheduleTaskRun: (taskId, agentId) =>
            request(`/forge/tasks/${taskId}/run`, {
                method: 'POST',
                body: JSON.stringify({ agent_id: agentId }),
            }),
        listTaskRuns: (taskId) => request(`/forge/tasks/${taskId}/runs`),
        // AP-74: live project activity summary (digest + Conductor view).
        getProjectActivity: (projectId) =>
            request(`/forge/projects/${projectId}/activity`),

        // Conductor management.
        getConductor: () => request('/forge/conductor'),
        runConductorTick: () => request('/forge/conductor/tick', { method: 'POST' }),
        runConductorPlan: () => request('/forge/conductor/plan', { method: 'POST' }),
        runConductorReport: () => request('/forge/conductor/report', { method: 'POST' }),

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
        listMcpServers: (includeAuto = true) => request(`/forge/mcp-servers?include_auto=${includeAuto}`),
        getDispatchPreview: (agentId, projectId) => request(
            `/forge/agents/${agentId}/dispatch-preview${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''}`
        ),
        listConversations: (agentId) => request(`/forge/agents/${agentId}/conversations`),
        // ADR 008 / AP-93: wipe agent memory for one scope.
        clearConversation: (agentId, scope_key) => request(
            `/forge/agents/${agentId}/conversations/clear`,
            { method: 'POST', body: JSON.stringify({ scope_key }) },
        ),
        // ADR 008 / AP-93: cancel in-flight dispatch; pauses an active run
        // when the scope is a task scope.
        stopChat: (agentId, scope_key) => request(
            `/forge/agents/${agentId}/chat/stop`,
            { method: 'POST', body: JSON.stringify({ scope_key }) },
        ),
        // ADR 009 / E2: is a turn live for this scope right now? Keeps the
        // Stop button available while anything runs (no 10-min heuristic).
        scopeLive: (agentId, scope_key) => request(
            `/forge/agents/${agentId}/scope-live?scope_key=${encodeURIComponent(scope_key)}`,
        ),
        // AP-179: messages queued behind the active turn in this conversation,
        // for the "queued" pills. Oldest first.
        listQueued: (agentId, scope_key) => request(
            `/forge/agents/${agentId}/queued?scope_key=${encodeURIComponent(scope_key)}`,
        ),
        getConversation: (agentId, projectId, taskId) => {
            const params = new URLSearchParams();
            if (projectId) params.set('project_id', projectId);
            if (taskId) params.set('task_id', taskId);
            const qs = params.toString() ? `?${params}` : '';
            return request(`/forge/agents/${agentId}/conversation${qs}`);
        },
    },
};
