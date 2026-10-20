// Connected apps shown in the top-bar app switcher (Google/Atlassian style).
// Static, build-time: VITE_CONNECTED_APPS='[{"key":"ezine","name":"Ezine","description":"Design & prototypes","url":"http://localhost:4400"}]'
// No request is made to render the switcher; empty/invalid config hides it.
function parse(raw) {
    try {
        const list = JSON.parse(raw || '[]');
        return Array.isArray(list)
            ? list.filter((a) => a && a.key && a.name && /^https?:\/\//.test(a.url || '')).map((a) => ({ ...a, url: a.url.replace(/\/$/, '') }))
            : [];
    } catch {
        return [];
    }
}

export const CONNECTED_APPS = parse(import.meta.env.VITE_CONNECTED_APPS);

// Single sign-on handoff: POST the caller's Agentira token to the app's /auth/handoff
// (form POST, so the token never lands in a URL, history or Referer). The app validates it
// against this Agentira, sets its own session and redirects into itself.
export function openConnectedApp(app, { token = localStorage.getItem('agentira_token'), project = '', doc = document } = {}) {
    if (!token) { window.open(app.url, '_blank', 'noopener'); return; }
    const form = doc.createElement('form');
    form.method = 'POST';
    form.action = `${app.url}/auth/handoff`;
    form.target = '_blank';
    const input = doc.createElement('input');
    input.type = 'hidden'; input.name = 'token'; input.value = token;
    form.appendChild(input);
    if (project) { // carry the selected project so the app opens on the same one
        const p = doc.createElement('input');
        p.type = 'hidden'; p.name = 'project'; p.value = project;
        form.appendChild(p);
    }
    doc.body.appendChild(form);
    form.submit();
    form.remove();
}
