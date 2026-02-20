import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../context/AuthContext';
import {
    ChevronLeft,
    Clock,
    User,
    Tag,
    AlertCircle,
    MessageSquare,
    Trash2,
    Calendar
} from 'lucide-react';

export function TaskPage() {
    const { taskId } = useParams();
    const navigate = useNavigate();
    const { user } = useAuth();
    const [task, setTask] = useState(null);
    const [activities, setActivities] = useState([]);
    const [comment, setComment] = useState('');
    const [profiles, setProfiles] = useState([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const load = async () => {
            try {
                const data = await api.getTask(taskId);
                setTask(data);
                const actData = await api.getActivity(taskId);
                setActivities(actData);
                const profData = await api.getProjectMembers(data.project_id);
                setProfiles(profData);
            } catch (err) {
                console.error(err);
            } finally {
                setLoading(false);
            }
        };
        load();
    }, [taskId]);

    const handleComment = async (e) => {
        e.preventDefault();
        if (!comment.trim()) return;
        try {
            await api.addComment(taskId, { comment });
            setComment('');
            const actData = await api.getActivity(taskId);
            setActivities(actData);
        } catch (err) {
            alert(err.message);
        }
    };

    if (loading) return <div className="p-8 text-text-secondary">Loading task...</div>;
    if (!task) return <div className="p-8 text-red-400">Task not found.</div>;

    const priorityColors = {
        critical: '#ef4444',
        high: '#f97316',
        medium: '#eab308',
        low: '#6b7280',
    };

    return (
        <div className="flex-1 bg-bg-app overflow-y-auto">
            <div className="max-w-7xl mx-auto p-8">
                {/* Back Button */}
                <button
                    onClick={() => navigate(-1)}
                    className="flex items-center gap-2 text-sm text-text-secondary hover:text-text-primary mb-6 transition-colors"
                >
                    <ChevronLeft className="w-4 h-4" /> Back
                </button>

                <div className="flex flex-col lg:flex-row gap-12">
                    {/* Main Content */}
                    <div className="flex-1">
                        <h1 className="text-3xl font-bold text-text-primary mb-4">{task.title}</h1>

                        <div className="mb-10">
                            <h2 className="text-sm font-bold uppercase text-text-tertiary mb-3">Description</h2>
                            <div className="text-base text-text-secondary leading-relaxed bg-bg-card p-6 rounded-lg border border-border-subtle shadow-sm">
                                {task.description || "No description provided."}
                            </div>
                        </div>

                        <div className="space-y-8">
                            <h2 className="text-sm font-bold uppercase text-text-tertiary border-b border-border-subtle pb-2 flex items-center gap-2">
                                <MessageSquare className="w-4 h-4" /> Activity
                            </h2>

                            {/* Comment Input */}
                            <div className="flex gap-4">
                                <div className="w-10 h-10 rounded-full bg-accent-subtle flex items-center justify-center font-bold text-sm text-accent-primary">
                                    {user?.display_name?.[0]?.toUpperCase() || 'U'}
                                </div>
                                <form onSubmit={handleComment} className="flex-1">
                                    <textarea
                                        className="w-full bg-bg-card border border-border-subtle text-sm p-4 rounded-lg focus:outline-none focus:border-accent-primary transition-colors h-24 resize-none shadow-sm"
                                        placeholder="Add a comment..."
                                        value={comment}
                                        onChange={e => setComment(e.target.value)}
                                    />
                                    <div className="mt-2 flex justify-end">
                                        <button className="btn btn-primary">Add Comment</button>
                                    </div>
                                </form>
                            </div>

                            {/* Activity Feed */}
                            <div className="space-y-8 mt-8">
                                {activities.map(act => (
                                    <div key={act.id} className="flex gap-4 group">
                                        <div className="w-10 h-10 rounded-full bg-bg-card border border-border-subtle flex items-center justify-center font-bold text-xs text-text-tertiary shadow-sm">
                                            {act.actor?.[0]?.toUpperCase() || '?'}
                                        </div>
                                        <div className="flex-1">
                                            <div className="flex items-center gap-3 mb-1">
                                                <span className="text-sm font-bold text-text-primary">{act.actor}</span>
                                                <span className="text-xs text-text-tertiary">
                                                    {new Date(act.created_at).toLocaleDateString()} at {new Date(act.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                                </span>
                                            </div>
                                            <div className="text-sm text-text-secondary">
                                                <span className="text-accent-primary font-medium mr-1">{act.action}</span>
                                                {act.detail}
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>

                    {/* Sidebar / Properties */}
                    <div className="w-full lg:w-80 space-y-8">
                        <div className="bg-bg-card border border-border-subtle rounded-xl p-6 shadow-sm">
                            <h3 className="text-xs font-bold uppercase text-text-tertiary mb-6 pb-2 border-b border-border-subtle/50">Details</h3>

                            <div className="space-y-6">
                                <div>
                                    <label className="text-[10px] font-bold uppercase text-text-tertiary block mb-2">Status</label>
                                    <span className={`text-xs px-2.5 py-1 rounded font-bold uppercase tracking-wider
                                        ${task.status === 'done' ? 'bg-green-500/20 text-green-400' : 'bg-accent-subtle text-accent-primary'}
                                    `}>
                                        {task.status.replace('_', ' ')}
                                    </span>
                                </div>

                                <div>
                                    <label className="text-[10px] font-bold uppercase text-text-tertiary block mb-2">Priority</label>
                                    <div className="flex items-center gap-2">
                                        <div className="w-2 h-2 rounded-full" style={{ backgroundColor: priorityColors[task.priority] }} />
                                        <span className="text-sm text-text-secondary capitalize">{task.priority}</span>
                                    </div>
                                </div>

                                <div>
                                    <label className="text-[10px] font-bold uppercase text-text-tertiary block mb-2">Assignee</label>
                                    <div className="flex items-center gap-2">
                                        <div className="w-6 h-6 rounded-full bg-accent-subtle flex items-center justify-center text-[10px] font-bold text-accent-primary">
                                            {task.assignee ? task.assignee[0].toUpperCase() : '?'}
                                        </div>
                                        <span className="text-sm text-text-secondary">{task.assignee || 'Unassigned'}</span>
                                    </div>
                                </div>

                                <div>
                                    <label className="text-[10px] font-bold uppercase text-text-tertiary block mb-2">Labels</label>
                                    <div className="flex flex-wrap gap-1.5">
                                        {(task.tags || []).length > 0 ? task.tags.map(t => (
                                            <span key={t} className="text-[10px] font-medium bg-bg-app px-2 py-0.5 rounded border border-border-subtle text-text-secondary">
                                                {t}
                                            </span>
                                        )) : <span className="text-xs text-text-tertiary italic">None</span>}
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div className="bg-bg-card border border-border-subtle rounded-xl p-6 shadow-sm">
                            <h3 className="text-xs font-bold uppercase text-text-tertiary mb-4">Timestamps</h3>
                            <div className="space-y-3">
                                <div className="flex items-center gap-2 text-text-tertiary">
                                    <Calendar className="w-3.5 h-3.5" />
                                    <span className="text-xs">Created: {new Date(task.created_at).toLocaleDateString()}</span>
                                </div>
                                <div className="flex items-center gap-2 text-text-tertiary">
                                    <Clock className="w-3.5 h-3.5" />
                                    <span className="text-xs">Updated: {new Date(task.updated_at).toLocaleDateString()}</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
