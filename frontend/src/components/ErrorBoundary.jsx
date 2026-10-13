import React from 'react';
import { reportError } from '../telemetry';

// Catches render crashes so the user gets a way out instead of a blank page,
// and reports the crash (with an id they can quote to support).
export class ErrorBoundary extends React.Component {
    constructor(props) {
        super(props);
        this.state = { errorId: null };
    }

    static getDerivedStateFromError() {
        return { errorId: '…' };
    }

    componentDidCatch(error, info) {
        const errorId = reportError(error, { component: String(info?.componentStack || '').slice(0, 1500) });
        this.setState({ errorId });
    }

    render() {
        if (!this.state.errorId) return this.props.children;
        return (
            <div role="alert" style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--surface-base, #111)', color: 'var(--text-primary, #eee)', padding: '16px' }}>
                <div style={{ maxWidth: '420px', textAlign: 'center' }}>
                    <h1 style={{ fontSize: '18px', margin: '0 0 8px' }}>Something went wrong</h1>
                    <p style={{ fontSize: '13px', color: 'var(--text-muted, #999)', margin: '0 0 16px' }}>
                        We've been notified. Reloading usually fixes it.
                        <br />Error id: <code>{this.state.errorId}</code>
                    </p>
                    <button type="button" className="btn btn-primary" onClick={() => window.location.reload()}>Reload</button>
                </div>
            </div>
        );
    }
}
