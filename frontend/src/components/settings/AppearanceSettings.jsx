import React, { useEffect, useState } from 'react';
import { Check } from 'lucide-react';
import { THEMES, getTheme, setTheme, subscribeTheme } from '../../lib/theme';

// Miniature app window so the choice is visible before it is applied.
function Preview({ theme }) {
    const c = theme === 'light'
        ? { app: '#ffffff', nav: '#f6f8fa', card: '#ffffff', line: '#d8dee4', text: '#1f2328', accent: '#6e56cf' }
        : { app: '#0e1117', nav: '#161b22', card: '#1c2128', line: '#30363d', text: '#f0f3f6', accent: '#c9b8ff' };
    return (
        <div style={{ display: 'flex', height: 74, borderRadius: 8, overflow: 'hidden', border: `1px solid ${c.line}`, background: c.app }}>
            <div style={{ width: 26, background: c.nav, borderRight: `1px solid ${c.line}`, padding: 6, display: 'flex', flexDirection: 'column', gap: 4 }}>
                <div style={{ height: 4, borderRadius: 2, background: c.accent }} />
                <div style={{ height: 4, borderRadius: 2, background: c.line }} />
                <div style={{ height: 4, borderRadius: 2, background: c.line }} />
            </div>
            <div style={{ flex: 1, padding: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
                <div style={{ height: 5, width: '55%', borderRadius: 2, background: c.text, opacity: .75 }} />
                <div style={{ flex: 1, borderRadius: 5, background: c.card, border: `1px solid ${c.line}` }} />
            </div>
        </div>
    );
}

function ThemeCard({ theme, active, onSelect }) {
    return (
        <button
            type="button"
            onClick={onSelect}
            aria-pressed={active}
            style={{
                flex: 1, textAlign: 'left', cursor: 'pointer', padding: 10, borderRadius: 12,
                background: 'var(--surface-card)',
                border: `1px solid ${active ? 'var(--accent-primary)' : 'var(--border-subtle)'}`,
                boxShadow: active ? '0 0 0 1px var(--accent-primary)' : 'none',
            }}
        >
            <Preview theme={theme.id} />
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, margin: '10px 0 2px' }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>{theme.label}</span>
                {active && <Check style={{ width: 13, height: 13, color: 'var(--accent-primary)' }} />}
            </div>
            <div style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>{theme.hint}</div>
        </button>
    );
}

export function AppearanceSettings() {
    const [theme, setLocal] = useState(getTheme);

    useEffect(() => subscribeTheme(setLocal), []);

    return (
        <div style={{ maxWidth: 560 }}>
            <h2 style={{ fontSize: 17, fontWeight: 600, margin: '0 0 6px', color: 'var(--text-primary)' }}>Appearance</h2>
            <p style={{ fontSize: 12.5, color: 'var(--text-tertiary)', margin: '0 0 20px' }}>
                Choose how Agentira looks. The change applies right away and is remembered on this device.
            </p>

            <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.1em', color: 'var(--text-tertiary)', marginBottom: 10 }}>DAY / NIGHT</div>
            <div style={{ display: 'flex', gap: 12 }}>
                {THEMES.map(t => (
                    <ThemeCard key={t.id} theme={t} active={theme === t.id} onSelect={() => setTheme(t.id)} />
                ))}
            </div>
        </div>
    );
}
