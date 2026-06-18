import React from 'react';
import logoMark from '../assets/logo-mark.svg';

// Phase-0 smoke route: proves the real Agentira design tokens are loaded,
// .agentira-glow paints with the rotating conic border, surface ramp + brand
// + status dots all read from the canonical CSS variables.
export function DevGlow() {
    const surfaces = ['sunken', 'base', 'raised', 'nav', 'card', 'hover'];
    const brand = ['brand-lavender', 'brand-teal', 'pulse-blue', 'accent-cyan', 'accent-purple'];
    const semantic = ['success', 'warning', 'danger', 'info'];
    const statusDots = [
        ['backlog', 'var(--text-muted)'],
        ['todo', 'var(--pulse-blue)'],
        ['in-progress', 'var(--warning)'],
        ['review', 'var(--accent-purple)'],
        ['done', 'var(--success)'],
    ];
    const agentRings = ['agent-ring-1', 'agent-ring-2', 'agent-ring-3', 'agent-ring-4', 'agent-ring-5', 'agent-conductor'];

    const sectionTitle = {
        font: 'var(--weight-semibold) var(--text-11)/1 var(--font-sans)',
        textTransform: 'uppercase',
        letterSpacing: 'var(--tracking-eyebrow)',
        color: 'var(--text-section)',
        marginBottom: 'var(--space-8)',
    };

    return (
        <div style={{
            minHeight: '100vh',
            padding: 'var(--space-16)',
            background: 'var(--surface-base)',
            color: 'var(--text-primary)',
            font: 'var(--type-body)',
        }}>
            <header style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-8)', marginBottom: 'var(--space-16)' }}>
                <img src={logoMark} alt="" width={36} height={36} style={{ borderRadius: 'var(--radius-lg)' }} />
                <div>
                    <div style={{ font: 'var(--type-page-title)' }}>Agentira tokens — Phase 0 smoke</div>
                    <div style={{ font: 'var(--type-meta)', color: 'var(--text-muted)' }}>Dark baseline, design system v1</div>
                </div>
            </header>

            <section style={{ marginBottom: 'var(--space-16)' }}>
                <div style={sectionTitle}>Live state · .agentira-glow</div>
                <div
                    className="agentira-glow"
                    style={{
                        width: 280, height: 88,
                        borderRadius: 'var(--radius-xl)',
                        background: 'var(--surface-card)',
                        border: '1px solid var(--border-default)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 'var(--space-6)',
                        font: 'var(--type-card-title)',
                        color: 'var(--pulse-blue)',
                    }}
                >
                    <span style={{ width: 8, height: 8, borderRadius: 'var(--radius-pill)', background: 'var(--pulse-blue)', boxShadow: 'var(--glow-pulse)' }} />
                    RUN ACTIVE
                </div>
            </section>

            <section style={{ marginBottom: 'var(--space-16)' }}>
                <div style={sectionTitle}>Surface ramp</div>
                <div style={{ display: 'flex', gap: 'var(--space-4)' }}>
                    {surfaces.map(s => (
                        <div key={s} style={{
                            width: 120, height: 72,
                            background: `var(--surface-${s})`,
                            border: '1px solid var(--border-default)',
                            borderRadius: 'var(--radius-lg)',
                            display: 'flex', alignItems: 'flex-end', padding: 'var(--space-6)',
                            font: 'var(--type-meta)', color: 'var(--text-muted)',
                        }}>
                            --surface-{s}
                        </div>
                    ))}
                </div>
            </section>

            <section style={{ marginBottom: 'var(--space-16)' }}>
                <div style={sectionTitle}>Brand + accents</div>
                <div style={{ display: 'flex', gap: 'var(--space-8)', flexWrap: 'wrap' }}>
                    {brand.map(t => (
                        <span key={t} style={{
                            display: 'inline-flex', alignItems: 'center', gap: 'var(--space-4)',
                            padding: 'var(--space-3) var(--space-6)',
                            borderRadius: 'var(--radius-pill)',
                            background: 'var(--surface-card)',
                            border: '1px solid var(--border-default)',
                            font: 'var(--type-meta)', color: 'var(--text-tertiary)',
                        }}>
                            <span style={{ width: 10, height: 10, borderRadius: 'var(--radius-pill)', background: `var(--${t})` }} />
                            {t}
                        </span>
                    ))}
                </div>
            </section>

            <section style={{ marginBottom: 'var(--space-16)' }}>
                <div style={sectionTitle}>Status dots</div>
                <div style={{ display: 'flex', gap: 'var(--space-10)' }}>
                    {statusDots.map(([label, color]) => (
                        <span key={label} style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-3)', font: 'var(--type-meta)', color: 'var(--text-tertiary)' }}>
                            <span style={{ width: 8, height: 8, borderRadius: 'var(--radius-pill)', background: color }} />
                            {label}
                        </span>
                    ))}
                </div>
            </section>

            <section style={{ marginBottom: 'var(--space-16)' }}>
                <div style={sectionTitle}>Semantic</div>
                <div style={{ display: 'flex', gap: 'var(--space-8)' }}>
                    {semantic.map(t => (
                        <div key={t} style={{
                            width: 96, height: 36,
                            background: `var(--tint-${t})`,
                            border: `1px solid var(--${t})`,
                            color: `var(--${t})`,
                            borderRadius: 'var(--radius-md)',
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            font: 'var(--type-meta)',
                        }}>{t}</div>
                    ))}
                </div>
            </section>

            <section>
                <div style={sectionTitle}>Agent identity ring</div>
                <div style={{ display: 'flex', gap: 'var(--space-6)' }}>
                    {agentRings.map(t => (
                        <span key={t} title={t} style={{
                            width: 32, height: 32, borderRadius: 'var(--radius-pill)',
                            background: `var(--${t})`,
                            border: '2px solid var(--surface-base)',
                            boxShadow: '0 0 0 1px var(--border-default)',
                        }} />
                    ))}
                </div>
            </section>
        </div>
    );
}
