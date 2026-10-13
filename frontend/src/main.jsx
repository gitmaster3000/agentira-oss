import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import './index.css';
import './styles.css';
import './tokens/compat.css';
import { applyStoredTheme } from './lib/theme';
import { startTelemetry } from './telemetry';
import { ErrorBoundary } from './components/ErrorBoundary';

startTelemetry();
applyStoredTheme();

ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
        <ErrorBoundary>
            <App />
        </ErrorBoundary>
    </React.StrictMode>
);
