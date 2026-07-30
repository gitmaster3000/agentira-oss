import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

afterEach(() => cleanup());

// jsdom in this setup exposes `window.localStorage` as a bare object, so the
// Storage methods the app relies on are missing. Give tests a real in-memory one.
if (typeof localStorage.getItem !== 'function') {
    const store = new Map();
    Object.defineProperty(window, 'localStorage', {
        configurable: true,
        value: {
            getItem: (k) => (store.has(String(k)) ? store.get(String(k)) : null),
            setItem: (k, v) => store.set(String(k), String(v)),
            removeItem: (k) => store.delete(String(k)),
            clear: () => store.clear(),
        },
    });
}
