/**
 * Shared markdown renderer for description fields (epic + task + later
 * project / Run summary). GFM-enabled (tables, task lists, strikethrough,
 * autolinks).
 *
 * Styling uses Tailwind utility classes via `components` so the rendered
 * output matches the rest of the app — no `prose` plugin needed, no global
 * CSS leak.
 *
 * AP-39: replaces the plain-text `<p whitespace-pre-wrap>` rendering that
 * showed `##` and `|` characters literally.
 */

import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';


const COMPONENTS = {
    h1: (p) => <h1 className="text-xl font-semibold text-text-primary mt-4 mb-2" {...p} />,
    h2: (p) => <h2 className="text-lg font-semibold text-text-primary mt-3 mb-2" {...p} />,
    h3: (p) => <h3 className="text-base font-semibold text-text-primary mt-2 mb-1" {...p} />,
    p:  (p) => <p className="text-sm text-text-secondary leading-relaxed my-2" {...p} />,
    ul: (p) => <ul className="list-disc pl-6 my-2 text-sm text-text-secondary space-y-0.5" {...p} />,
    ol: (p) => <ol className="list-decimal pl-6 my-2 text-sm text-text-secondary space-y-0.5" {...p} />,
    li: (p) => <li className="text-sm text-text-secondary" {...p} />,
    a:  (p) => <a className="text-accent-primary underline hover:text-accent-primary-hover" target="_blank" rel="noopener noreferrer" {...p} />,
    code({ inline, className, children, ...props }) {
        if (inline) {
            return <code className="px-1.5 py-0.5 rounded bg-bg-panel border border-border-subtle text-[0.85em] font-mono text-text-primary" {...props}>{children}</code>;
        }
        // Editor-style block: a deep "code well" surface, an optional language
        // label bar (from ```lang fences), and horizontal scroll for long lines.
        const lang = /language-(\w+)/.exec(className || '')?.[1];
        return (
            <div className="my-2 rounded-lg border border-border-subtle overflow-hidden">
                {lang && (
                    <div className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-text-tertiary bg-bg-card border-b border-border-subtle">
                        {lang}
                    </div>
                )}
                <pre className="p-3 overflow-x-auto" style={{ background: 'var(--surface-sunken)' }}>
                    <code className={`text-[12.5px] leading-relaxed font-mono text-text-primary ${className || ''}`} {...props}>{children}</code>
                </pre>
            </div>
        );
    },
    blockquote: (p) => <blockquote className="border-l-2 border-border-subtle pl-3 my-2 text-sm text-text-tertiary italic" {...p} />,
    table: (p) => (
        <div className="my-2 overflow-x-auto">
            <table className="text-sm border border-border-subtle rounded" {...p} />
        </div>
    ),
    thead: (p) => <thead className="bg-bg-panel" {...p} />,
    th: (p) => <th className="px-2 py-1.5 text-left text-text-primary font-medium border-b border-border-subtle" {...p} />,
    td: (p) => <td className="px-2 py-1 text-text-secondary border-t border-border-subtle align-top" {...p} />,
    hr: (p) => <hr className="my-3 border-border-subtle" {...p} />,
    strong: (p) => <strong className="text-text-primary font-semibold" {...p} />,
    em: (p) => <em className="text-text-primary italic" {...p} />,
};


export function Markdown({ children, className = '' }) {
    if (!children) return null;
    return (
        <div className={className}>
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
                {String(children)}
            </ReactMarkdown>
        </div>
    );
}
