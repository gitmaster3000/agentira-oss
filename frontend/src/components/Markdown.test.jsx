import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Markdown } from './Markdown';

describe('Markdown — code rendering', () => {
    it('renders inline code inline, not as a code block', () => {
        const { container } = render(<Markdown>{'use the `npm run dev` command'}</Markdown>);
        const code = container.querySelector('code');
        expect(code).not.toBeNull();
        expect(code.textContent).toBe('npm run dev');
        // A block would wrap the code in <pre>; inline code must not.
        expect(code.closest('pre')).toBeNull();
        expect(container.querySelector('pre')).toBeNull();
    });

    it('still renders fenced blocks as blocks, with the language label', () => {
        const { container } = render(<Markdown>{'```js\nconst a = 1;\n```'}</Markdown>);
        const pre = container.querySelector('pre');
        expect(pre).not.toBeNull();
        expect(pre.textContent).toContain('const a = 1;');
        expect(screen.getByText('js')).toBeInTheDocument();
    });

    it('renders a fenced block without a language as a block', () => {
        const { container } = render(<Markdown>{'```\nplain block\n```'}</Markdown>);
        const pre = container.querySelector('pre');
        expect(pre).not.toBeNull();
        expect(pre.textContent).toContain('plain block');
    });
});
