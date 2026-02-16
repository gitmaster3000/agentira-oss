/** @type {import('tailwindcss').Config} */
export default {
    content: [
        "./index.html",
        "./src/**/*.{js,ts,jsx,tsx}",
    ],
    theme: {
        extend: {
            colors: {
                'bg-app': 'var(--bg-app)',
                'bg-panel': 'var(--bg-panel)',
                'bg-card': 'var(--bg-card)',
                'bg-hover': 'var(--bg-hover)',
                'border-subtle': 'var(--border-subtle)',
                'border-active': 'var(--border-active)',
                'primary': 'var(--text-primary)',
                'secondary': 'var(--text-secondary)',
                'tertiary': 'var(--text-tertiary)',
                'accent-primary': 'var(--accent-primary)',
                'accent-hover': 'var(--accent-hover)',
                'accent-subtle': 'var(--accent-subtle)',

                'status-backlog': 'var(--status-backlog)',
                'status-todo': 'var(--status-todo)',
                'status-inprogress': 'var(--status-inprogress)',
                'status-review': 'var(--status-review)',
                'status-done': 'var(--status-done)',
            }
        },
    },
    plugins: [],
}
