/* Day/night theme. The whole palette lives in CSS custom properties
   (tokens/colors.css); switching themes only flips <html data-theme>. */

export const THEMES = [
    { id: 'dark', label: 'Night', hint: 'Dim surfaces, easy on the eyes at night.' },
    { id: 'light', label: 'Day', hint: 'Bright surfaces for well-lit rooms.' },
];

const STORAGE_KEY = 'theme';
const listeners = new Set();

function isValid(theme) {
    return THEMES.some(t => t.id === theme);
}

export function getTheme() {
    let stored = null;
    try {
        stored = localStorage.getItem(STORAGE_KEY);
    } catch {
        /* private mode / storage disabled */
    }
    return isValid(stored) ? stored : 'dark';
}

export function applyStoredTheme() {
    document.documentElement.dataset.theme = getTheme();
}

export function setTheme(theme) {
    if (!isValid(theme)) return;
    try {
        localStorage.setItem(STORAGE_KEY, theme);
    } catch {
        /* private mode / storage disabled */
    }
    document.documentElement.dataset.theme = theme;
    listeners.forEach(fn => fn(theme));
}

export function toggleTheme() {
    setTheme(getTheme() === 'light' ? 'dark' : 'light');
}

export function subscribeTheme(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
}
