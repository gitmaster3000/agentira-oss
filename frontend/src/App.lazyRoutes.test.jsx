/**
 * Regression: AP-433's lazy-route split (App.jsx) converted these page
 * imports to `lazy(() => import(path))`, which React resolves via
 * `.default`. All of these pages only ever had named exports (no
 * `export default`) — every route resolved to `undefined` and crashed
 * with React error #306 ("Element type is invalid") on first navigation,
 * in prod, for every Forge/Chat page.
 *
 * This asserts the two halves App.jsx's `.then(m => ({ default: m.X }))`
 * fix depends on: the module has no default export (so plain lazy(import)
 * would still break), and the named export exists and is a component.
 */
import React, { Suspense, lazy } from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

class CaughtError extends React.Component {
    constructor(props) { super(props); this.state = { error: null }; }
    static getDerivedStateFromError(error) { return { error }; }
    render() {
        if (this.state.error) return <div data-testid="caught-error">{this.state.error.message}</div>;
        return this.props.children;
    }
}

const LAZY_ROUTES = [
    ['./pages/forge/ForgeOverview', 'ForgeOverview'],
    ['./pages/forge/AgentsDashboard', 'AgentsDashboard'],
    ['./pages/forge/RuntimesDashboard', 'RuntimesDashboard'],
    ['./pages/forge/AgentDetail', 'AgentDetail'],
    ['./pages/forge/RunsDashboard', 'RunsDashboard'],
    ['./pages/forge/RunDetail', 'RunDetail'],
    ['./pages/forge/ConductorPage', 'ConductorPage'],
    ['./pages/forge/ForgeSettings', 'ForgeSettings'],
];

describe('App.jsx lazy-loaded forge routes', () => {
    it.each(LAZY_ROUTES)('%s has no default export (confirms named-export shape)', async (path) => {
        const mod = await import(/* @vite-ignore */ path);
        expect(mod.default).toBeUndefined();
    });

    it.each(LAZY_ROUTES)('%s exports %s as a function', async (path, name) => {
        const mod = await import(/* @vite-ignore */ path);
        expect(typeof mod[name]).toBe('function');
    });

});

// Isolated repro of the exact failure mechanism (React error #306), against
// a throwaway module with only a named export — independent of any real
// page's own dependencies (router/API), so this stays hermetic.
const namedExportOnly = () => Promise.resolve({ Widget: () => <div data-testid="widget">ok</div> });

async function renderLazy(thunk) {
    const LazyWidget = lazy(thunk);
    render(
        <CaughtError>
            <Suspense fallback={<div data-testid="loading">loading</div>}>
                <LazyWidget />
            </Suspense>
        </CaughtError>
    );
    await waitFor(() => {
        expect(screen.queryByTestId('loading')).not.toBeInTheDocument();
    });
}

describe('React.lazy + named-only export (mechanism repro)', () => {
    it('lazy(() => import(path)) on a named-export-only module throws error #306', async () => {
        await renderLazy(namedExportOnly); // the bug: no .then(m => ({ default: m.Widget }))
        expect(screen.getByTestId('caught-error')).toBeInTheDocument();
        expect(screen.getByTestId('caught-error').textContent).toMatch(/Element type is invalid|306/);
    });

    it('lazy(() => import(path).then(m => ({ default: m.Widget }))) renders fine — the App.jsx fix', async () => {
        await renderLazy(() => namedExportOnly().then(m => ({ default: m.Widget })));
        expect(screen.queryByTestId('caught-error')).not.toBeInTheDocument();
        expect(screen.getByTestId('widget')).toHaveTextContent('ok');
    });
});
