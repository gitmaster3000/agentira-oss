import { describe, it, expect } from 'vitest';
import { appForUrl, openConnectedApp } from './connectedApps';

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

describe('appForUrl', () => {
    const apps = [{ key: 'ezine', name: 'Ezine', url: 'http://localhost:4400' }];
    it('finds the configured app by exact origin', () => {
        expect(appForUrl('http://localhost:4400/?doc=d1', apps)).toBe(apps[0]);
    });
    it('rejects other origins and junk, so a login is never handed to an unlisted site', () => {
        expect(appForUrl('http://localhost:4401/', apps)).toBeNull();
        expect(appForUrl('https://localhost:4400/', apps)).toBeNull();
        expect(appForUrl('http://evil.test/?x=http://localhost:4400', apps)).toBeNull();
        expect(appForUrl('/relative', apps)).toBeNull();
        expect(appForUrl('', apps)).toBeNull();
    });
});

describe('openConnectedApp returnTo', () => {
    it('adds the return path and posts in the same tab for /sso', () => {
        let captured;
        const doc = document.implementation.createHTMLDocument('t');
        const origCreate = doc.createElement.bind(doc);
        doc.createElement = (tag) => { const el = origCreate(tag); if (tag === 'form') { el.submit = () => { captured = { target: el.target, fields: Object.fromEntries(new FormData(el)) }; }; } return el; };
        openConnectedApp({ url: 'http://localhost:4400' }, { token: 'jwt-abc', returnTo: '/?doc=d1', target: '_self', doc });
        expect(captured).toEqual({ target: '_self', fields: { token: 'jwt-abc', return: '/?doc=d1' } });
    });
});
