import React, { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { api } from '../api';
import { ROUTES } from '../routes';
import { Layout } from '../components/Layout';
import { formatDistanceToNow } from 'date-fns'; // Assuming date-fns is installed for relative time

export function ActivityFeedPage() {
    const { projectId } = useParams();
    const [activity, setActivity] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        const fetchActivity = async () => {
            try {
                setLoading(true);
                const data = await api.getProjectActivity(projectId, { limit: 50 }); // Adjust limit as needed
                setActivity(data);
            } catch (err) {
                setError("Failed to load activity feed.");
                console.error("Failed to load activity feed:", err);
            } finally {
                setLoading(false);
            }
        };

        if (projectId) {
            fetchActivity();
        }
    }, [projectId]);

    if (loading) {
        return (
            <Layout>
                <div className="p-6 text-center text-text-secondary">Loading activity feed...</div>
            </Layout>
        );
    }

    if (error) {
        return (
            <Layout>
                <div className="p-6 text-center text-red-500">{error}</div>
            </Layout>
        );
    }

    return (
        <Layout>
            <div className="p-6">
                <h1 className="text-2xl font-bold text-text-primary mb-6">Project Activity Feed</h1>

                {activity.length === 0 ? (
                    <div className="text-center text-text-secondary">No activity to display for this project yet.</div>
                ) : (
                    <div className="space-y-4">
                        {activity.map(entry => (
                            <div key={entry.id} className="bg-bg-card border border-border-subtle rounded-md p-4 flex items-start gap-3">
                                <div className="w-8 h-8 rounded-full bg-accent-subtle flex items-center justify-center font-bold text-sm text-accent-primary border border-accent-primary/20">
                                    {entry.actor?.[0]?.toUpperCase() || 'U'}
                                </div>
                                <div className="flex-1">
                                    <p className="text-sm text-text-primary">
                                        <span className="font-semibold">{entry.actor}</span> {entry.action}
                                        {entry.task_id && entry.task_title && (
                                            <> on task <Link to={`${ROUTES.STUDIO_BOARD(projectId)}/task/${entry.task_id}`} className="text-accent-primary hover:underline">{entry.task_title}</Link></>
                                        )}
                                    </p>
                                    {entry.detail && <p className="text-xs text-text-secondary mt-1">{entry.detail}</p>}
                                    <p className="text-xs text-text-tertiary mt-1">
                                        {formatDistanceToNow(new Date(entry.created_at), { addSuffix: true })}
                                    </p>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </Layout>
    );
}
