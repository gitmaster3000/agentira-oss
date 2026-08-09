import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';

const css = readFileSync('src/tokens/colors.css', 'utf8');

function tokensIn(selector) {
    const block = css.slice(css.indexOf(selector) + selector.length);
    const body = block.slice(0, block.indexOf('}'));
    // Tokens whose value is itself a var() reference follow the theme on their
    // own, so they don't need a second declaration.
    return new Set([...body.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)]
        .filter(m => !m[2].trim().startsWith('var('))
        .map(m => m[1]));
}

describe('colour tokens', () => {
    it('gives every night token a day value', () => {
        const night = tokensIn(':root {');
        const day = tokensIn(':root[data-theme="light"] {');
        expect(night.size).toBeGreaterThan(30);
        expect([...night].filter(t => !day.has(t))).toEqual([]);
    });
});
