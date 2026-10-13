/**
 * Shared building blocks for settings pages. One look, one control per kind of
 * value: text → TextField/TextArea, yes/no → Toggle, pick-one → ChoiceList,
 * number → TextField type="number". Styled to match the account Settings page.
 */

import React, { useState } from 'react';
import { ChevronDown, Info } from 'lucide-react';


/** ⓘ button; the explanation shows on hover, focus or click — never inline. */
export function InfoTip({ children }) {
    const [open, setOpen] = useState(false);
    return (
        <span style={{ position: 'relative', display: 'inline-flex', verticalAlign: 'middle', marginLeft: 6 }}
            onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
            <button type="button" aria-label="More info" aria-expanded={open}
                onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen((o) => !o); }}
                onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
                style={{ display: 'inline-flex', background: 'none', border: 'none', padding: 0, cursor: 'help', color: 'var(--text-tertiary)' }}>
                <Info style={{ width: 13, height: 13 }} />
            </button>
            {open && (
                <span role="tooltip" style={{
                    position: 'absolute', left: -6, top: 'calc(100% + 6px)', zIndex: 50, width: 280,
                    padding: '9px 11px', borderRadius: 9, fontSize: 11.5, lineHeight: 1.5, fontWeight: 400,
                    letterSpacing: 'normal', textTransform: 'none', whiteSpace: 'normal',
                    color: 'var(--text-primary)', background: 'var(--surface-card)',
                    border: '1px solid var(--border-default)', boxShadow: '0 6px 20px rgba(0,0,0,.35)',
                }}>{children}</span>
            )}
        </span>
    );
}

export const SettingsSection = ({ title, description, action, children }) => (
    <div style={{ maxWidth: 620 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
            <h2 style={{ fontSize: 17, fontWeight: 600, margin: 0, color: 'var(--text-primary)' }}>{title}</h2>
            {action}
        </div>
        {description && (
            <p style={{ fontSize: 12.5, color: 'var(--text-muted)', margin: '0 0 22px' }}>{description}</p>
        )}
        {!description && <div style={{ height: 18 }} />}
        {children}
    </div>
);

export const SubLabel = ({ children, hint }) => (
    <div style={{ margin: '26px 0 12px' }}>
        <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.08em', color: 'var(--text-muted)' }}>
            {children}
            {hint && <InfoTip>{hint}</InfoTip>}
        </div>
    </div>
);

export const Field = ({ label, hint, htmlFor, children }) => (
    <div style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 6 }}>
            <label htmlFor={htmlFor} style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>{label}</label>
            {hint && <InfoTip>{hint}</InfoTip>}
        </div>
        {children}
    </div>
);

const controlStyle = (mono) => ({
    width: '100%', padding: '10px 13px', borderRadius: 10,
    background: 'var(--surface-card)', border: '1px solid var(--border-default)',
    fontSize: mono ? 12.5 : 13, color: 'var(--text-primary)',
    fontFamily: mono ? 'ui-monospace,monospace' : undefined,
    outline: 'none', transition: 'border-color .15s',
});
const focusRing = {
    onFocus: (e) => { e.target.style.borderColor = 'var(--accent-primary)'; },
    onBlur: (e) => { e.target.style.borderColor = 'var(--border-default)'; },
};

export const TextField = ({ mono, style, ...rest }) => (
    <input style={{ ...controlStyle(mono), ...style }} {...focusRing} {...rest} />
);

export const TextArea = ({ mono, rows = 4, ...rest }) => (
    <textarea rows={rows} style={{ ...controlStyle(mono), resize: 'vertical', lineHeight: 1.5 }} {...focusRing} {...rest} />
);

export function Toggle({ checked, onChange, label, hint, id }) {
    return (
        <div style={{
            display: 'flex', alignItems: 'flex-start', gap: 14, padding: '12px 14px', borderRadius: 10,
            background: 'var(--surface-card)', border: '1px solid var(--border-default)',
        }}>
            <div style={{ flex: 1, minWidth: 0 }}>
                <label htmlFor={id} style={{ fontSize: 13, color: 'var(--text-primary)', cursor: 'pointer' }}>{label}</label>
                {hint && <InfoTip>{hint}</InfoTip>}
            </div>
            <button type="button" role="switch" id={id} aria-checked={checked} aria-label={label}
                onClick={() => onChange(!checked)}
                style={{
                    width: 36, height: 20, borderRadius: 10, border: 'none', padding: 2, flexShrink: 0, cursor: 'pointer',
                    background: checked ? 'var(--accent-primary)' : 'var(--border-default)',
                    transition: 'background .15s', marginTop: 1,
                }}>
                <span style={{
                    display: 'block', width: 16, height: 16, borderRadius: '50%', background: '#fff',
                    transform: checked ? 'translateX(16px)' : 'none', transition: 'transform .15s',
                }} />
            </button>
        </div>
    );
}

/**
 * Pick-one list. options: [{ value, label, help, tone? }] — tone 'warn' tints a
 * choice that needs care. `name` groups the radios.
 */
export function ChoiceList({ name, value, onChange, options, disabled }) {
    return (
        <div role="radiogroup" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {options.map((o) => {
                const on = value === o.value;
                return (
                    <label key={o.value} style={{
                        display: 'flex', alignItems: 'flex-start', gap: 11, padding: '11px 13px', borderRadius: 10,
                        cursor: disabled ? 'default' : 'pointer',
                        background: 'var(--surface-card)',
                        border: `1px solid ${on ? 'var(--accent-primary)' : 'var(--border-default)'}`,
                        boxShadow: on ? '0 0 0 1px var(--accent-primary)' : 'none',
                        opacity: disabled ? 0.6 : 1,
                    }}>
                        <input type="radio" name={name} checked={on} disabled={disabled}
                            onChange={() => onChange(o.value)}
                            style={{ marginTop: 3, accentColor: 'var(--accent-primary)' }} />
                        <span style={{ flex: 1, minWidth: 0 }}>
                            <span style={{ display: 'block', fontSize: 13, color: o.tone === 'warn' ? '#fbbf24' : 'var(--text-primary)' }}>
                                {o.label}
                                {o.help && <InfoTip>{o.help}</InfoTip>}
                            </span>
                        </span>
                    </label>
                );
            })}
        </div>
    );
}

export const Card = ({ children, tone, style }) => (
    <div style={{
        padding: 14, borderRadius: 12, background: 'var(--surface-card)',
        border: `1px solid ${tone === 'danger' ? 'rgba(239,68,68,.35)' : 'var(--border-default)'}`,
        ...style,
    }}>{children}</div>
);

export const Notice = ({ tone = 'info', children }) => {
    const c = tone === 'warn'
        ? { color: '#fbbf24', background: 'rgba(251,191,36,.08)', border: 'rgba(251,191,36,.25)' }
        : tone === 'error'
            ? { color: '#f87171', background: 'rgba(248,113,113,.08)', border: 'rgba(248,113,113,.25)' }
            : { color: '#4ade80', background: 'rgba(74,222,128,.08)', border: 'rgba(74,222,128,.25)' };
    return (
        <div style={{
            padding: '7px 12px', borderRadius: 9, fontSize: 12, marginBottom: 12,
            color: c.color, background: c.background, border: `1px solid ${c.border}`,
        }}>{children}</div>
    );
};

export const Button = ({ variant = 'primary', icon: Icon, children, style, ...rest }) => {
    const v = {
        primary: { background: 'var(--accent-primary,var(--brand-lavender))', color: 'var(--accent-on)', border: 'none' },
        secondary: { background: 'var(--surface-card)', color: 'var(--text-primary)', border: '1px solid var(--border-default)' },
        danger: { background: 'transparent', color: '#f87171', border: '1px solid rgba(239,68,68,.4)' },
    }[variant];
    return (
        <button type="button" {...rest} style={{
            display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 16px', borderRadius: 9,
            fontSize: 13, fontWeight: 600, cursor: rest.disabled ? 'default' : 'pointer',
            opacity: rest.disabled ? 0.4 : 1, ...v, ...style,
        }}>
            {Icon && <Icon style={{ width: 14, height: 14 }} />}
            {children}
        </button>
    );
};

/** "Advanced" reveal for technical detail — hidden by default. */
export function Advanced({ label = 'Advanced', children }) {
    const [open, setOpen] = useState(false);
    return (
        <div style={{ marginTop: 14 }}>
            <button type="button" onClick={() => setOpen((s) => !s)} aria-expanded={open}
                style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 12, color: 'var(--text-tertiary)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>
                <ChevronDown style={{ width: 13, height: 13, transform: open ? 'none' : 'rotate(-90deg)', transition: 'transform .15s' }} />
                {label}
            </button>
            {open && <div style={{ marginTop: 12 }}>{children}</div>}
        </div>
    );
}
