import React from 'react';
import { BrowserRouter, Routes, Route, Navigate, useParams } from 'react-router-dom';
import { Layout } from './components/Layout';
import { Board } from './pages/Board';
import { AuthProvider, useAuth } from './context/AuthContext';
import { Landing } from './pages/Landing';
import { Login } from './pages/Login';
import { Signup } from './pages/Signup';
import { GitHubCallback } from './pages/GitHubCallback';
import { Settings } from './pages/Settings';
import { StudioDashboard } from './pages/StudioDashboard';
import { TaskPage } from './pages/TaskPage';
import { EpicPage } from './pages/EpicPage';
import { ForgeLayout } from './pages/forge/ForgeLayout';
import { ForgeOverview } from './pages/forge/ForgeOverview';
import { AgentsDashboard } from './pages/forge/AgentsDashboard';
import { RuntimesDashboard } from './pages/forge/RuntimesDashboard';
import { AgentDetail } from './pages/forge/AgentDetail';
import { RunsDashboard } from './pages/forge/RunsDashboard';
import { RunDetail } from './pages/forge/RunDetail';
import { ROUTES } from './routes';

// Old "Welcome" stub replaced by StudioDashboard — see pages/StudioDashboard.jsx

function RequireAuth({ children }) {
    const { user, loading } = useAuth();
    if (loading) return <div>Loading...</div>;
    if (!user) return <Navigate to={ROUTES.WELCOME} replace />;
    return children;
}

function RedirectIfAuth({ children }) {
    const { user, loading } = useAuth();
    if (loading) return <div>Loading...</div>;
    if (user) return <Navigate to={ROUTES.STUDIO} replace />;
    return children;
}

function RootRedirect() {
    const { user, loading } = useAuth();
    if (loading) return <div>Loading...</div>;
    return user ? <Navigate to={ROUTES.STUDIO} replace /> : <Navigate to={ROUTES.WELCOME} replace />;
}

function LegacyBoardRedirect() {
    const { projectId } = useParams();
    return <Navigate to={ROUTES.STUDIO_BOARD(projectId)} replace />;
}

export default function App() {
    return (
        <AuthProvider>
            <BrowserRouter>
                <Routes>
                    {/* Public routes */}
                    <Route path={ROUTES.WELCOME} element={<RedirectIfAuth><Landing /></RedirectIfAuth>} />
                    <Route path={ROUTES.LOGIN} element={<RedirectIfAuth><Login /></RedirectIfAuth>} />
                    <Route path={ROUTES.SIGNUP} element={<RedirectIfAuth><Signup /></RedirectIfAuth>} />
                    <Route path={ROUTES.GITHUB_CALLBACK} element={<GitHubCallback />} />

                    {/* Studio routes (authenticated) */}
                    <Route path={ROUTES.STUDIO} element={
                        <RequireAuth><Layout /></RequireAuth>
                    }>
                        <Route index element={<StudioDashboard />} />
                        <Route path="board/:projectId" element={<Board />} />
                        <Route path="settings" element={<Settings />} />
                        <Route path="tasks/:taskId" element={<TaskPage />} />
                        <Route path="epics/:epicId" element={<EpicPage />} />
                    </Route>

                    {/* Root redirect */}
                    <Route path="/" element={<RootRedirect />} />

                    {/* Legacy redirects */}
                    <Route path="/board/:projectId" element={<LegacyBoardRedirect />} />
                    <Route path="/settings" element={<Navigate to={ROUTES.STUDIO_SETTINGS} replace />} />

                    {/* Forge routes */}
                    <Route path="/forge" element={<RequireAuth><ForgeLayout /></RequireAuth>}>
                        <Route index element={<ForgeOverview />} />
                        <Route path="agents" element={<AgentsDashboard />} />
                        <Route path="agents/:agentId" element={<AgentDetail />} />
                        <Route path="runtimes" element={<RuntimesDashboard />} />
                        <Route path="runs" element={<RunsDashboard />} />
                        <Route path="runs/:runId" element={<RunDetail />} />
                    </Route>

                    {/* Catch-all */}
                    <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
            </BrowserRouter>
        </AuthProvider>
    );
}
