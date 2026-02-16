import React, { useState } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export function Login() {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const { login } = useAuth();
    const navigate = useNavigate();
    const location = useLocation();
    const successMessage = location.state?.message;

    // Default admin: admin / admin123

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError('');
        try {
            await login(username, password);
            const from = location.state?.from?.pathname || '/';
            navigate(from, { replace: true });
        } catch (err) {
            setError('Invalid username or password');
        }
    };

    return (
        <div className="flex min-h-screen items-center justify-center bg-gray-900 text-gray-100">
            <div className="w-full max-w-sm p-8 space-y-6 bg-gray-800 rounded-lg shadow-xl border border-gray-700">
                <div className="text-center">
                    <h1 className="text-3xl font-bold bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent">AgentIRA</h1>
                    <p className="mt-2 text-sm text-gray-400">Sign in to continue</p>
                </div>

                {successMessage && <div className="p-3 text-sm text-green-400 bg-green-900/20 border border-green-800 rounded">{successMessage}</div>}
                {error && <div className="p-3 text-sm text-red-400 bg-red-900/20 border border-red-800 rounded">{error}</div>}

                <form onSubmit={handleSubmit} className="space-y-4">
                    <div>
                        <label className="block text-sm font-medium text-gray-400">Username</label>
                        <input
                            type="text"
                            value={username}
                            onChange={(e) => setUsername(e.target.value)}
                            className="w-full mt-1 px-3 py-2 bg-gray-900 border border-gray-700 rounded focus:ring-2 focus:ring-blue-500 focus:outline-none"
                            placeholder="e.g. admin"
                            autoFocus
                        />
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-gray-400">Password</label>
                        <input
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            className="w-full mt-1 px-3 py-2 bg-gray-900 border border-gray-700 rounded focus:ring-2 focus:ring-blue-500 focus:outline-none"
                            placeholder="••••••••"
                        />
                    </div>
                    <button
                        type="submit"
                        className="w-full py-2 px-4 bg-blue-600 hover:bg-blue-500 text-white font-semibold rounded shadow transition-colors"
                    >
                        Sign In
                    </button>
                </form>

                <div className="text-center text-sm text-gray-400">
                    Don't have an account? <Link to="/signup" className="text-blue-400 hover:underline">Sign Up</Link>
                </div>

                <div className="text-center text-xs text-gray-500">
                    <p>Default Admin: admin / admin123</p>
                </div>
            </div>
        </div>
    );
}
