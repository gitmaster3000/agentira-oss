import React, { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { api } from '../api';
import { ROUTES } from '../routes';
import {
    Pencil, ClipboardList, Users, Bot, ArrowRight,
    Zap, Shield, GitBranch, Mail, ChevronRight,
} from 'lucide-react';

export function Landing() {
    const { loginWithOAuth } = useAuth();
    const navigate = useNavigate();
    const [authConfig, setAuthConfig] = useState({ google: false, github: false });
    const googleBtnRef = useRef(null);
    const [error, setError] = useState('');

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
    }, [authConfig.google]);

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
            desc: 'Drag-and-drop task management with full lifecycle tracking, status transitions, and real-time updates.',
            color: 'var(--status-todo)',
        },
        {
            icon: Bot,
            title: 'AI-Native MCP',
            desc: 'Built-in MCP server lets AI agents create, update, and manage tasks alongside your team — natively.',
            color: 'var(--status-review)',
        },
        {
            icon: Users,
            title: 'Team RBAC',
            desc: 'Granular roles and permissions for every team member, service account, and AI agent.',
            color: 'var(--status-done)',
        },
        {
            icon: Zap,
            title: 'Real-Time Sync',
            desc: 'Instant updates across all connected clients. See changes the moment they happen.',
            color: 'var(--status-inprogress)',
        },
        {
            icon: Shield,
            title: 'Secure by Default',
            desc: 'API key authentication, OAuth providers, and scoped permissions keep your data safe.',
            color: 'var(--accent-primary)',
        },
        {
            icon: GitBranch,
            title: 'Git Integration',
            desc: 'Link branches, commits, and PRs directly to tasks. Track development progress in context.',
            color: 'var(--status-backlog)',
        },
    ];

    return (
        <div className="h-full bg-bg-app flex flex-col overflow-y-auto">

            {/* ── Header ─────────────────────────────────────────── */}
            <header className="border-b sticky top-0 z-50" style={{ backgroundColor: 'var(--bg-panel)', borderColor: 'var(--border-subtle)' }}>
                <div className="max-w-5xl mx-auto h-16 flex items-center justify-between px-6">
                    <nav className="hidden sm:flex items-center gap-6 text-body-md text-text-secondary">
                        <a href="#features" className="hover:text-text-primary transition-colors">Features</a>
                        <a href="#about" className="hover:text-text-primary transition-colors">About</a>
                        <a href="#contact" className="hover:text-text-primary transition-colors">Contact</a>
                    </nav>
                    <div className="flex items-center gap-2">
                        <Link to={ROUTES.LOGIN} className="btn-ghost btn text-body-md">Sign In</Link>
                        <Link to={ROUTES.SIGNUP} className="btn btn-primary text-body-md">Sign Up</Link>
                    </div>
                </div>
            </header>

            {/* ── Hero ────────────────────────────────────────────── */}
            <section className="px-6 pt-24 pb-20">
                <div className="max-w-3xl mx-auto text-center space-y-6">
                    <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-xl text-label-sm border" style={{ borderColor: 'var(--border-subtle)', color: 'var(--accent-primary)', backgroundColor: 'var(--accent-subtle)' }}>
                        <Zap className="w-3.5 h-3.5" />
                        Now with AI-native MCP support
                    </div>

                    <h1 className="text-display-sm md:text-display-md font-bold text-text-primary leading-tight">
                        Task management for{' '}
                        <span style={{ color: 'var(--accent-primary)' }}>humans & AI agents</span>
                    </h1>
                    <p className="text-body-lg text-text-secondary max-w-xl mx-auto">
                        A shared workspace where your team and AI agents plan, track, and ship together. Powered by MCP so any agent can plug in natively.
                    </p>

                    {error && (
                        <div className="p-3 text-body-sm text-red-400 bg-red-900/20 border border-red-800 rounded-md max-w-sm mx-auto">
                            {error}
                        </div>
                    )}

                    {/* CTA Auth Card */}
                    <div className="card max-w-sm mx-auto space-y-3 mt-4" style={{ borderRadius: '16px', padding: '24px' }}>
                        <h3 className="text-title-md text-text-primary text-center">Get started for free</h3>

                        {authConfig.google && (
                            <div ref={googleBtnRef} className="flex justify-center" />
                        )}
                        {authConfig.github && (
                            <button
                                onClick={handleGitHub}
                                className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-body-md font-medium transition-colors border"
                                style={{ backgroundColor: 'var(--bg-panel)', borderColor: 'var(--border-subtle)', color: 'var(--text-primary)' }}
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

                        <Link
                            to={ROUTES.SIGNUP}
                            className="btn w-full justify-center text-body-md font-medium rounded-xl border transition-colors"
                            style={{ backgroundColor: 'var(--bg-panel)', borderColor: 'var(--border-subtle)', color: 'var(--text-primary)' }}
                        >
                            Sign up with email
                        </Link>

                        <p className="text-body-sm text-text-tertiary text-center pt-1">
                            Already have an account?{' '}
                            <Link to={ROUTES.LOGIN} className="font-medium" style={{ color: 'var(--accent-primary)' }}>Sign in</Link>
                        </p>
                    </div>
                </div>
            </section>

            {/* ── Features ───────────────────────────────────────── */}
            <section id="features" className="px-6 py-20 border-t" style={{ borderColor: 'var(--border-subtle)' }}>
                <div className="max-w-5xl mx-auto">
                    <div className="text-center mb-14">
                        <h2 className="text-headline-md font-bold text-text-primary">Everything you need to ship</h2>
                        <p className="text-body-lg text-text-secondary mt-3 max-w-lg mx-auto">
                            Built for teams that work with AI. Every feature designed for both human and agent workflows.
                        </p>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
                        {features.map((f) => (
                            <div key={f.title} className="card space-y-3" style={{ borderRadius: '16px' }}>
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
                </div>
            </section>

            {/* ── About ──────────────────────────────────────────── */}
            <section id="about" className="px-6 py-20 border-t" style={{ borderColor: 'var(--border-subtle)', backgroundColor: 'var(--bg-panel)' }}>
                <div className="max-w-3xl mx-auto text-center space-y-6">
                    <h2 className="text-headline-md font-bold text-text-primary">Why AgentIRA?</h2>
                    <p className="text-body-lg text-text-secondary">
                        Most project management tools treat AI as an afterthought. AgentIRA was built from the ground up with a dual-interface architecture: a REST API for humans and an MCP server for AI agents — sharing the same workspace, permissions, and data.
                    </p>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-8 pt-6">
                        <div className="space-y-2">
                            <div className="text-display-sm font-bold" style={{ color: 'var(--accent-primary)' }}>2</div>
                            <div className="text-label-lg text-text-primary">Interfaces</div>
                            <div className="text-body-sm text-text-tertiary">REST API + MCP Server</div>
                        </div>
                        <div className="space-y-2">
                            <div className="text-display-sm font-bold" style={{ color: 'var(--status-done)' }}>100%</div>
                            <div className="text-label-lg text-text-primary">Open Protocol</div>
                            <div className="text-body-sm text-text-tertiary">Built on Model Context Protocol</div>
                        </div>
                        <div className="space-y-2">
                            <div className="text-display-sm font-bold" style={{ color: 'var(--status-inprogress)' }}>0</div>
                            <div className="text-label-lg text-text-primary">Vendor Lock-in</div>
                            <div className="text-body-sm text-text-tertiary">Works with any MCP-compatible agent</div>
                        </div>
                    </div>
                </div>
            </section>

            {/* ── How It Works ───────────────────────────────────── */}
            <section className="px-6 py-20 border-t" style={{ borderColor: 'var(--border-subtle)' }}>
                <div className="max-w-4xl mx-auto">
                    <div className="text-center mb-14">
                        <h2 className="text-headline-md font-bold text-text-primary">How it works</h2>
                        <p className="text-body-lg text-text-secondary mt-3">Get up and running in minutes.</p>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-8">
                        {[
                            { step: '1', title: 'Create a workspace', desc: 'Sign up, create a project, and invite your team members.' },
                            { step: '2', title: 'Connect your agents', desc: 'Point any MCP-compatible AI agent at your AgentIRA server with an API key.' },
                            { step: '3', title: 'Ship together', desc: 'Humans and AI manage tasks on the same board with full visibility.' },
                        ].map((s) => (
                            <div key={s.step} className="text-center space-y-3">
                                <div
                                    className="w-12 h-12 rounded-xl mx-auto flex items-center justify-center text-title-lg font-bold"
                                    style={{ backgroundColor: 'var(--accent-subtle)', color: 'var(--accent-primary)' }}
                                >
                                    {s.step}
                                </div>
                                <h3 className="text-title-sm text-text-primary">{s.title}</h3>
                                <p className="text-body-sm text-text-secondary">{s.desc}</p>
                            </div>
                        ))}
                    </div>
                </div>
            </section>

            {/* ── Contact ────────────────────────────────────────── */}
            <section id="contact" className="px-6 py-20 border-t" style={{ borderColor: 'var(--border-subtle)', backgroundColor: 'var(--bg-panel)' }}>
                <div className="max-w-lg mx-auto text-center space-y-6">
                    <h2 className="text-headline-md font-bold text-text-primary">Get in touch</h2>
                    <p className="text-body-lg text-text-secondary">
                        Have questions, feedback, or want to collaborate? We'd love to hear from you.
                    </p>
                    <a
                        href="mailto:hello@flowty.dev"
                        className="btn btn-primary text-body-md gap-2 mx-auto"
                    >
                        <Mail className="w-4 h-4" />
                        hello@flowty.dev
                    </a>
                </div>
            </section>

            {/* ── CTA Banner ─────────────────────────────────────── */}
            <section className="px-6 py-16 border-t" style={{ borderColor: 'var(--border-subtle)' }}>
                <div className="max-w-3xl mx-auto text-center space-y-5">
                    <h2 className="text-headline-sm font-bold text-text-primary">Ready to build with AI?</h2>
                    <p className="text-body-lg text-text-secondary">
                        Join AgentIRA and start managing tasks with your team and AI agents today.
                    </p>
                    <Link to={ROUTES.SIGNUP} className="btn btn-primary text-body-md gap-2">
                        Get Started Free <ArrowRight className="w-4 h-4" />
                    </Link>
                </div>
            </section>

            {/* ── Footer ─────────────────────────────────────────── */}
            <footer className="border-t px-6 py-8" style={{ borderColor: 'var(--border-subtle)', backgroundColor: 'var(--bg-panel)' }}>
                <div className="max-w-5xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
                    <div className="flex items-center gap-2">
                        <span className="w-7 h-7 rounded-md flex items-center justify-center" style={{ backgroundColor: 'rgba(201, 184, 255, 0.1)' }}>
                            <Pencil className="w-4 h-4" style={{ color: 'var(--accent-primary)' }} />
                        </span>
                        <span className="text-title-sm font-semibold text-text-primary">AgentIRA Studio</span>
                    </div>
                    <div className="flex items-center gap-6 text-body-sm text-text-tertiary">
                        <a href="#features" className="hover:text-text-secondary transition-colors">Features</a>
                        <a href="#about" className="hover:text-text-secondary transition-colors">About</a>
                        <a href="#contact" className="hover:text-text-secondary transition-colors">Contact</a>
                    </div>
                    <div className="text-label-sm text-text-tertiary">
                        &copy; 2026 AgentIRA. Built for AI-Human collaboration.
                    </div>
                </div>
            </footer>
        </div>
    );
}
