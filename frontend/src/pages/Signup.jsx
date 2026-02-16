import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { api } from '../api';

export function Signup() {
    const [formData, setFormData] = useState({
        name: '',
        display_name: '',
        password: ''
    });
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const navigate = useNavigate();

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError('');
        setLoading(true);
        try {
            await api.signup(formData);
            navigate('/login', { state: { message: 'Signup successful! Please log in.' } });
        } catch (err) {
            setError(err.message || 'Signup failed');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="flex min-h-screen items-center justify-center bg-gray-900 text-gray-100">
            <div className="w-full max-w-sm p-8 space-y-6 bg-gray-800 rounded-lg shadow-xl border border-gray-700">
                <div className="text-center">
                    <h1 className="text-3xl font-bold bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent">AgentIRA</h1>
                    <p className="mt-2 text-sm text-gray-400">Create your account</p>
                </div>

                {error && <div className="p-3 text-sm text-red-400 bg-red-900/20 border border-red-800 rounded">{error}</div>}

                <form onSubmit={handleSubmit} className="space-y-4">
                    <div>
                        <label className="block text-sm font-medium text-gray-400">Username</label>
                        <input
                            type="text"
                            required
                            value={formData.name}
                            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                            className="w-full mt-1 px-3 py-2 bg-gray-900 border border-gray-700 rounded focus:ring-2 focus:ring-blue-500 focus:outline-none"
                            placeholder="e.g. jdoe"
                            autoFocus
                        />
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-gray-400">Display Name</label>
                        <input
                            type="text"
                            value={formData.display_name}
                            onChange={(e) => setFormData({ ...formData, display_name: e.target.value })}
                            className="w-full mt-1 px-3 py-2 bg-gray-900 border border-gray-700 rounded focus:ring-2 focus:ring-blue-500 focus:outline-none"
                            placeholder="e.g. John Doe"
                        />
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-gray-400">Password</label>
                        <input
                            type="password"
                            required
                            value={formData.password}
                            onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                            className="w-full mt-1 px-3 py-2 bg-gray-900 border border-gray-700 rounded focus:ring-2 focus:ring-blue-500 focus:outline-none"
                            placeholder="••••••••"
                        />
                    </div>
                    <button
                        type="submit"
                        disabled={loading}
                        className="w-full py-2 px-4 bg-purple-600 hover:bg-purple-500 text-white font-semibold rounded shadow transition-colors disabled:opacity-50"
                    >
                        {loading ? 'Creating Account...' : 'Sign Up'}
                    </button>
                </form>

                <div className="text-center text-sm text-gray-400">
                    Already have an account? <Link to="/login" className="text-blue-400 hover:underline">Sign In</Link>
                </div>
            </div>
        </div>
    );
}
