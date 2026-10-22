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

// Connected app that owns `url` (exact origin match), or null. Gate for /sso: a login is only
// ever handed to an app listed in VITE_CONNECTED_APPS, never to an arbitrary return address.
export function appForUrl(url, apps = CONNECTED_APPS) {
    let origin;
    try { origin = new URL(url).origin; } catch { return null; }
    return apps.find((a) => new URL(a.url).origin === origin) || null;
}

// Single sign-on handoff: POST the caller's Agentira token to the app's /auth/handoff
// (form POST, so the token never lands in a URL, history or Referer). The app validates it
// against this Agentira, sets its own session and redirects into itself (or to `returnTo`, a path).
export function openConnectedApp(app, { token = localStorage.getItem('agentira_token'), project = '', returnTo = '', target = '_blank', doc = document } = {}) {
    if (!token) { window.open(app.url, '_blank', 'noopener'); return; }
    const form = doc.createElement('form');
    form.method = 'POST';
    form.action = `${app.url}/auth/handoff`;
    form.target = target;
    const add = (name, value) => {
        const input = doc.createElement('input');
        input.type = 'hidden'; input.name = name; input.value = value;
        form.appendChild(input);
    };
    add('token', token);
    if (project) add('project', project); // carry the selected project so the app opens on the same one
    if (returnTo) add('return', returnTo); // page the user asked for in the app (/sso)
    doc.body.appendChild(form);
    form.submit();
    form.remove();
}
