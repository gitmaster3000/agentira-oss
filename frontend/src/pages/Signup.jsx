import React, { useState, useEffect, useRef } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { api } from '../api';
import { ROUTES } from '../routes';
import { Pencil } from 'lucide-react';

// Module-level: a component defined inside Signup remounts every render and
// the inputs lose focus per keystroke.
const Shell = ({ children }) => (
    <div className="h-full bg-bg-app flex flex-col items-center justify-center px-4 overflow-y-auto">
        <div className="w-full max-w-sm space-y-6">
            <Link to={ROUTES.WELCOME} className="flex items-center gap-2.5 justify-center mb-2">
                <span className="w-9 h-9 rounded-md flex items-center justify-center" style={{ backgroundColor: 'rgba(201, 184, 255, 0.1)' }}>
                    <Pencil className="w-5 h-5" style={{ color: 'var(--accent-primary)' }} />
                </span>
                <span className="text-title-sm font-semibold text-text-primary">AgentIRA</span>
            </Link>
            <div className="card space-y-5">{children}</div>
        </div>
    </div>
);

export function Signup() {
    const [searchParams] = useSearchParams();
    const inviteCode = searchParams.get('invite') || '';

    const [formData, setFormData] = useState({ name: '', display_name: '', email: '', password: '' });
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const [invite, setInvite] = useState(null);        // { role, org_name, ... }
    const [inviteError, setInviteError] = useState('');
    const [authConfig, setAuthConfig] = useState({ google: false, github: false });
    const { loginWithOAuth } = useAuth();
    const navigate = useNavigate();
    const googleBtnRef = useRef(null);

    // Validate the invite code up front.
    useEffect(() => {
        if (!inviteCode) { setInviteError('no-code'); return; }
        api.getInvite(inviteCode)
            .then(setInvite)
            .catch((err) => setInviteError(err.message || 'Invalid invite'));
    }, [inviteCode]);

    useEffect(() => {
        api.getAuthConfig().then(setAuthConfig).catch(() => {});
    }, []);

    useEffect(() => {
        if (!invite || !authConfig.google || !window.google?.accounts?.id) return;
        window.google.accounts.id.initialize({
            client_id: authConfig.google_client_id,
            callback: handleGoogleResponse,
        });
        if (googleBtnRef.current) {
            window.google.accounts.id.renderButton(googleBtnRef.current, {
                theme: 'filled_black', size: 'large', width: 320, text: 'signup_with',
            });
        }
    }, [authConfig.google, invite]);

    const handleGoogleResponse = async (response) => {
        setError('');
        try {
            const data = await api.googleAuth(response.credential, inviteCode);
            await loginWithOAuth(data);
            navigate(ROUTES.STUDIO, { replace: true });
        } catch (err) {
            setError(err.message || 'Google sign-up failed');
        }
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError('');
        setLoading(true);
        try {
            const data = await api.acceptInvite(inviteCode, formData);
            await loginWithOAuth(data);   // sets auth state from { user, token }
            navigate(ROUTES.STUDIO, { replace: true });
        } catch (err) {
            setError(err.message || 'Signup failed');
        } finally {
            setLoading(false);
        }
    };

    // No invite code, or an invalid/expired one → invite-only gate.
    if (inviteError) {
        return (
            <Shell>
                <h2 className="text-headline-sm text-text-primary text-center">Invite required</h2>
                <p className="text-body-sm text-text-tertiary text-center">
                    {inviteError === 'no-code'
                        ? 'Sign-up is invite-only. Ask your admin for an invite link.'
                        : `This invite can't be used: ${inviteError}`}
                </p>
                <p className="text-body-sm text-text-tertiary text-center">
                    Already have an account?{' '}
                    <Link to={ROUTES.LOGIN} className="font-medium" style={{ color: 'var(--accent-primary)' }}>Sign In</Link>
                </p>
            </Shell>
        );
    }

    if (!invite) {
        return <Shell><p className="text-body-sm text-text-tertiary text-center">Checking invite…</p></Shell>;
    }

    return (
        <Shell>
            <div className="text-center space-y-1">
                <h2 className="text-headline-sm text-text-primary">Create your account</h2>
                <p className="text-body-sm text-text-tertiary">
                    {invite.role === 'admin'
                        ? 'You\'re setting up a new organization as its admin.'
                        : `Joining ${invite.org_name || 'an organization'} as a member.`}
                </p>
            </div>

            {error && <div className="p-3 text-body-sm text-red-400 bg-red-900/20 border border-red-800 rounded-md">{error}</div>}

            {authConfig.google && (
                <div className="space-y-3">
                    <div ref={googleBtnRef} className="flex justify-center" />
                    <div className="relative">
                        <div className="absolute inset-0 flex items-center"><div className="w-full border-t" style={{ borderColor: 'var(--border-subtle)' }}></div></div>
                        <div className="relative flex justify-center text-label-sm"><span className="px-3 text-text-tertiary" style={{ backgroundColor: 'var(--bg-card)' }}>or</span></div>
                    </div>
                </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                    <label htmlFor="signup-username" className="text-label-md text-text-secondary mb-1 block">Username</label>
                    <input id="signup-username" name="username" type="text" autoComplete="username" required
                        value={formData.name} onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                        className="input" placeholder="e.g. jdoe" autoFocus />
                </div>
                <div>
                    <label htmlFor="signup-display-name" className="text-label-md text-text-secondary mb-1 block">Display Name</label>
                    <input id="signup-display-name" name="display_name" type="text" autoComplete="name"
                        value={formData.display_name} onChange={(e) => setFormData({ ...formData, display_name: e.target.value })}
                        className="input" placeholder="e.g. John Doe" />
                </div>
                <div>
                    <label htmlFor="signup-email" className="text-label-md text-text-secondary mb-1 block">Email</label>
                    <input id="signup-email" name="email" type="email" autoComplete="email" required
                        value={formData.email} onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                        className="input" placeholder="you@example.com" />
                </div>
                <div>
                    <label htmlFor="signup-password" className="text-label-md text-text-secondary mb-1 block">Password</label>
                    <input id="signup-password" name="password" type="password" autoComplete="new-password" required
                        value={formData.password} onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                        className="input" placeholder="••••••••" />
                </div>
                <button type="submit" disabled={loading} className="btn btn-primary w-full justify-center text-body-md">
                    {loading ? 'Creating Account…' : 'Create Account'}
                </button>
            </form>

            <p className="text-body-sm text-text-tertiary text-center">
                Already have an account?{' '}
                <Link to={ROUTES.LOGIN} className="font-medium" style={{ color: 'var(--accent-primary)' }}>Sign In</Link>
            </p>
        </Shell>
    );
}
