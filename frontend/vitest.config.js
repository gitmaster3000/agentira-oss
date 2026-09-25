import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Node 25+ ships a global localStorage that shadows jsdom's and is undefined
// without --localstorage-file, breaking every test that touches storage.
// Turn it off where the flag exists (older Nodes don't know it).
const noNodeWebStorage = process.allowedNodeEnvironmentFlags.has('--no-experimental-webstorage')
    ? ['--no-experimental-webstorage'] : [];

export default defineConfig({
    plugins: [react()],
    test: {
        environment: 'jsdom',
        globals: true,
        setupFiles: ['./src/test/setup.js'],
        include: ['src/**/*.test.{js,jsx}'],
        poolOptions: { forks: { execArgv: noNodeWebStorage } },
    },
});
