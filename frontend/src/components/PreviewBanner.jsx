import { useEffect } from 'react';

// Preview-ONLY banner. Renders only when the per-PR preview container injects
// VITE_PREVIEW_PR (see scripts/local-pr-preview.sh). In dev and prod that env
// var is undefined, so this component renders nothing — prod stays clean.
const PR = import.meta.env.VITE_PREVIEW_PR;
const BRANCH = import.meta.env.VITE_PREVIEW_BRANCH;
const REPO = 'gitmaster3000/agentira-frontend';

export function PreviewBanner() {
    const active = Boolean(PR);

    // Push the app down so the fixed banner never covers the real header.
    // Also expose the offset as a CSS var: `position: fixed` overlays (PulseDock)
    // ignore body padding, so they read this var to stay aligned with the header.
    useEffect(() => {
        if (!active) return;
        const prev = document.body.style.paddingTop;
        document.body.style.paddingTop = '44px';
        document.documentElement.style.setProperty('--app-top-offset', '44px');
        return () => {
            document.body.style.paddingTop = prev;
            document.documentElement.style.removeProperty('--app-top-offset');
        };
    }, [active]);

    if (!active) return null;

    return (
        <div
            style={{
                position: 'fixed',
                top: 0,
                left: 0,
                right: 0,
                height: 44,
                zIndex: 99999,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 16,
                fontSize: 14,
                fontWeight: 700,
                color: '#1a1300',
                backgroundColor: '#ffb020',
                backgroundImage:
                    'repeating-linear-gradient(45deg, rgba(0,0,0,0.08) 0 12px, transparent 12px 24px)',
                borderBottom: '2px solid #1a1300',
                boxShadow: '0 2px 8px rgba(0,0,0,0.25)',
                letterSpacing: 0.3,
            }}
        >
            <span>🧪 PREVIEW</span>
            <span>
                PR&nbsp;
                <a
                    href={`https://github.com/${REPO}/pull/${PR}`}
                    target="_blank"
                    rel="noreferrer"
                    style={{ color: '#1a1300', textDecoration: 'underline' }}
                >
                    #{PR}
                </a>
            </span>
            <span>
                branch&nbsp;
                <code style={{ fontWeight: 800 }}>{BRANCH}</code>
            </span>
            <span style={{ fontWeight: 500, opacity: 0.8 }}>local backend · :8111</span>
        </div>
    );
}
