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

    // Generic
    request,
};
