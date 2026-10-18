/**
 * Shared markdown renderer (see MarkdownImpl for styling and GFM notes).
 * The parser (react-markdown + remark-gfm, ~120 kB) loads on first use so it
 * stays out of the main bundle; until it arrives the raw text is shown, so
 * layout does not jump.
 */

import React, { lazy, Suspense } from 'react';

const MarkdownImpl = lazy(() => import('./MarkdownImpl'));

export const Markdown = React.memo(function Markdown({ children, className = '' }) {
    if (!children) return null;
    return (
        <Suspense fallback={<div className={`${className} whitespace-pre-wrap text-sm text-text-secondary`}>{String(children)}</div>}>
            <MarkdownImpl className={className}>{children}</MarkdownImpl>
        </Suspense>
    );
});
