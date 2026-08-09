import React from 'react';
import { ChevronDown } from 'lucide-react';

// Shared by the task side panel and the full task page, so a section behaves
// and reads the same in both places.
export function CollapsibleSection({ title, icon: Icon, sectionRef, open, onToggle, separated = false, children }) {
    return (
        <section
            ref={sectionRef}
            style={separated
                ? { borderTop: '1px solid var(--border-default)', marginTop: 20, paddingTop: 12 }
                : undefined}
        >
            <button
                type="button"
                aria-expanded={open}
                aria-label={`Toggle ${title} section`}
                onClick={onToggle}
                className="w-full flex items-center text-text-secondary hover:text-text-primary transition-colors"
                style={{ gap: 7, marginBottom: open ? 12 : 0, padding: '4px 0', textAlign: 'left' }}
            >
                <Icon className="w-3.5 h-3.5" />
                <span style={{ fontSize: 12.5, fontWeight: 800, letterSpacing: '.06em', textTransform: 'uppercase' }}>
                    {title}
                </span>
                <ChevronDown
                    className="w-3.5 h-3.5 ml-auto transition-transform"
                    style={{ transform: open ? 'rotate(0deg)' : 'rotate(-90deg)' }}
                />
            </button>
            {open && children}
        </section>
    );
}
