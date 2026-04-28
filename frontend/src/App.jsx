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
import { TaskPage } from './pages/TaskPage';
import { ROUTES } from './routes';

function Welcome() {
    return (
        <div className="flex-1 flex flex-col items-center justify-center text-secondary">
            <div className="text-center">
                <h2 className="text-2xl font-bold text-primary mb-2">Welcome to AgentIRA</h2>
                <p>Select a project from the sidebar to get started.</p>
            </div>
        </div>
    );
}

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
                        <Route index element={<Welcome />} />
                        <Route path="board/:projectId" element={<Board />} />
                        <Route path="settings" element={<Settings />} />
                        <Route path="tasks/:taskId" element={<TaskPage />} />
                    </Route>

                    {/* Root redirect */}
                    <Route path="/" element={<RootRedirect />} />

                    {/* Legacy redirects */}
                    <Route path="/board/:projectId" element={<LegacyBoardRedirect />} />
                    <Route path="/settings" element={<Navigate to={ROUTES.STUDIO_SETTINGS} replace />} />

                    {/* Forge routes — disabled for now */}
                    <Route path="/forge/*" element={<Navigate to={ROUTES.STUDIO} replace />} />

                    {/* Catch-all */}
                    <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
            </BrowserRouter>
        </AuthProvider>
    );
}
