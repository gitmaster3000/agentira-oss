import React, { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { api } from '../api';
import { ROUTES } from '../routes';
import { Pencil, ClipboardList, Users, Bot, ArrowRight } from 'lucide-react';

export function Landing() {
    const { loginWithOAuth } = useAuth();
    const navigate = useNavigate();
    const [authConfig, setAuthConfig] = useState({ google: false, github: false });
    const googleBtnRef = useRef(null);
    const [error, setError] = useState('');
    const [showAuth, setShowAuth] = useState(false);

    useEffect(() => {
        api.getAuthConfig().then(setAuthConfig).catch(() => {});
    }, []);

    useEffect(() => {
        if (!authConfig.google || !window.google?.accounts?.id || !googleBtnRef.current) return;
        window.google.accounts.id.initialize({
            client_id: authConfig.google_client_id,
            callback: handleGoogleResponse,
        });
        window.google.accounts.id.renderButton(googleBtnRef.current, {
            theme: 'filled_black',
            size: 'large',
            width: 320,
            text: 'continue_with',
        });
    }, [authConfig.google, showAuth]);

    const handleGoogleResponse = async (response) => {
        setError('');
        try {
            const data = await api.googleAuth(response.credential);
            await loginWithOAuth(data);
            navigate(ROUTES.STUDIO, { replace: true });
        } catch (err) {
            setError('Google sign-in failed');
        }
    };

    const handleGitHub = () => {
        if (!authConfig.github_client_id) return;
        const redirect = `${window.location.origin}${ROUTES.GITHUB_CALLBACK}`;
        window.location.href = `https://github.com/login/oauth/authorize?client_id=${authConfig.github_client_id}&redirect_uri=${encodeURIComponent(redirect)}&scope=user:email`;
    };

    const features = [
        {
            icon: ClipboardList,
            title: 'Kanban Boards',
            desc: 'Drag-and-drop task management with full lifecycle tracking and status transitions.',
            color: 'var(--status-todo)',
        },
        {
            icon: Bot,
            title: 'AI-Native MCP',
            desc: 'Built-in MCP server lets AI agents create, update, and manage tasks alongside your team.',
            color: 'var(--status-review)',
        },
        {
            icon: Users,
            title: 'Team RBAC',
            desc: 'Granular roles and permissions for every team member and service account.',
            color: 'var(--status-done)',
        },
    ];

    return (
        <div className="min-h-screen bg-bg-app flex flex-col overflow-auto">
            {/* ── Navbar ─────────────────────────────────────────── */}
            <header className="h-16 border-b bg-bg-panel flex items-center px-6 justify-between sticky top-0 z-50">
                <div className="flex items-center gap-2.5">
                    <span className="w-9 h-9 rounded-md flex items-center justify-center" style={{ backgroundColor: 'rgba(201, 184, 255, 0.1)' }}>
                        <Pencil className="w-5 h-5" style={{ color: 'var(--accent-primary)' }} />
                    </span>
                    <div className="flex flex-col leading-tight">
                        <span className="text-[10px] font-medium tracking-widest uppercase text-text-tertiary">Flowty</span>
                        <span className="text-title-sm font-semibold text-text-primary">Studio</span>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <Link to={ROUTES.LOGIN} className="btn-ghost btn text-body-md">Sign In</Link>
                    <button onClick={() => setShowAuth(true)} className="btn btn-primary text-body-md">
                        Get Started
                    </button>
                </div>
            </header>

            {/* ── Hero ────────────────────────────────────────────── */}
            <main className="flex-1 flex flex-col items-center px-6">
                <div className="max-w-2xl text-center pt-20 pb-12 space-y-5">
                    <h1 className="text-display-sm md:text-display-md font-bold text-text-primary leading-tight">
                        Task management for{' '}
                        <span style={{ color: 'var(--accent-primary)' }}>humans & AI agents</span>
                    </h1>
                    <p className="text-body-lg text-text-secondary max-w-lg mx-auto">
                        A shared workspace where your team and AI agents plan, track, and ship together. Powered by MCP so any agent can plug in natively.
                    </p>

                    {error && (
                        <div className="p-3 text-body-sm text-red-400 bg-red-900/20 border border-red-800 rounded-md max-w-sm mx-auto">
                            {error}
                        </div>
                    )}

                    {/* ── Auth Section ────────────────────────────────── */}
                    {!showAuth ? (
                        <div className="flex items-center justify-center gap-3 pt-4">
                            <button onClick={() => setShowAuth(true)} className="btn btn-primary text-body-md gap-2">
                                Get Started Free <ArrowRight className="w-4 h-4" />
                            </button>
                        </div>
                    ) : (
                        <div className="card max-w-sm mx-auto mt-6 space-y-4 animate-fade-in">
                            <h3 className="text-title-md text-text-primary text-center">Create your account</h3>

                            {/* OAuth */}
                            {authConfig.google && (
                                <div ref={googleBtnRef} className="flex justify-center" />
                            )}
                            {authConfig.github && (
                                <button
                                    onClick={handleGitHub}
                                    className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-body-md font-medium transition-colors border"
                                    style={{
                                        backgroundColor: 'var(--bg-panel)',
                                        borderColor: 'var(--border-subtle)',
                                        color: 'var(--text-primary)',
                                    }}
                                >
                                    <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/></svg>
                                    Continue with GitHub
                                </button>
                            )}

                            {(authConfig.google || authConfig.github) && (
                                <div className="relative">
                                    <div className="absolute inset-0 flex items-center"><div className="w-full border-t" style={{ borderColor: 'var(--border-subtle)' }}></div></div>
                                    <div className="relative flex justify-center text-label-sm"><span className="px-3 text-text-tertiary" style={{ backgroundColor: 'var(--bg-card)' }}>or</span></div>
                                </div>
                            )}

                            {/* Email signup link */}
                            <Link
                                to={ROUTES.SIGNUP}
                                className="btn w-full justify-center text-body-md font-medium rounded-xl border transition-colors"
                                style={{
                                    backgroundColor: 'var(--bg-panel)',
                                    borderColor: 'var(--border-subtle)',
                                    color: 'var(--text-primary)',
                                }}
                            >
                                Sign up with username & password
                            </Link>

                            <p className="text-body-sm text-text-tertiary text-center">
                                Already have an account?{' '}
                                <Link to={ROUTES.LOGIN} className="font-medium" style={{ color: 'var(--accent-primary)' }}>Sign in</Link>
                            </p>
                        </div>
                    )}
                </div>

                {/* ── Features ────────────────────────────────────── */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-5 max-w-3xl w-full pb-20">
                    {features.map((f) => (
                        <div key={f.title} className="card space-y-3">
                            <div
                                className="w-10 h-10 rounded-md flex items-center justify-center"
                                style={{ backgroundColor: f.color + '1a' }}
                            >
                                <f.icon className="w-5 h-5" style={{ color: f.color }} />
                            </div>
                            <h3 className="text-title-sm text-text-primary">{f.title}</h3>
                            <p className="text-body-sm text-text-secondary">{f.desc}</p>
                        </div>
                    ))}
                </div>
            </main>

            {/* ── Footer ──────────────────────────────────────────── */}
            <footer className="py-5 text-center text-label-sm text-text-tertiary border-t" style={{ borderColor: 'var(--border-subtle)' }}>
                Built for AI-Human collaboration
            </footer>
        </div>
    );
}
