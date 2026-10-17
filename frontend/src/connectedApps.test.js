import { describe, it, expect } from 'vitest';
import { openConnectedApp } from './connectedApps';

describe('openConnectedApp', () => {
    it('POSTs the token in a hidden form field, never in the URL', () => {
        let captured;
        const doc = document.implementation.createHTMLDocument('t');
        const origCreate = doc.createElement.bind(doc);
        doc.createElement = (tag) => { const el = origCreate(tag); if (tag === 'form') { el.submit = () => { captured = { action: el.action, method: el.method, fields: Object.fromEntries(new FormData(el)) }; }; } return el; };
        openConnectedApp({ url: 'http://localhost:4400' }, { token: 'jwt-abc', project: 'p42', doc });
        expect(captured.action).toBe('http://localhost:4400/auth/handoff');
        expect(captured.method).toBe('post');
        expect(captured.fields).toEqual({ token: 'jwt-abc', project: 'p42' });
        expect(captured.action).not.toContain('jwt-abc');
    });
});
