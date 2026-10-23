import { describe, it, expect } from 'vitest';
import { mcpAuthorizeTarget, postToMcp } from './mcpConnect';

describe('mcpAuthorizeTarget', () => {
    it('accepts the authorize URL on the configured MCP origin only', () => {
        expect(mcpAuthorizeTarget('http://localhost:8000/authorize?a=1', 'http://localhost:8000')?.search).toBe('?a=1');
        expect(mcpAuthorizeTarget('http://localhost:8000/other', 'http://localhost:8000')).toBeNull();
        expect(mcpAuthorizeTarget('http://evil.test/authorize', 'http://localhost:8000')).toBeNull();
        expect(mcpAuthorizeTarget('not a url', 'http://localhost:8000')).toBeNull();
        expect(mcpAuthorizeTarget('http://localhost:8000/authorize', '')).toBeNull();
    });
});

describe('postToMcp', () => {
    it('form-POSTs the token and the authorize params (not sso) to /authorize/sso', () => {
        const submitted = [];
        const doc = document.implementation.createHTMLDocument('x');
        const orig = doc.createElement.bind(doc);
        doc.createElement = (t) => { const el = orig(t); if (t === 'form') el.submit = () => submitted.push([el.method, el.action, Object.fromEntries(new FormData(el))]); return el; };
        postToMcp(new URL('http://localhost:8000/authorize?client_id=c&state=s&sso=0'), { token: 'jwt', doc });
        expect(submitted).toEqual([['post', 'http://localhost:8000/authorize/sso', { client_id: 'c', state: 's', token: 'jwt' }]]);
    });
});
