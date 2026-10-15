import React from 'react';
import { MessageSquare, Activity as ActivityIcon } from 'lucide-react';
import { CommentComposer } from './CommentComposer';

export const ActivityTab = React.memo(function ActivityTab({ activities }) {
    // Full, read-only timeline of everything that happened on the task
    // (status changes, comments, runs…). Posting comments lives on the Plan tab.
    return (
        <div className="max-w-3xl">
            <h2 className="text-sm font-bold uppercase text-text-tertiary mb-6 flex items-center gap-2">
                <ActivityIcon className="w-4 h-4" /> Activity
            </h2>
            {activities.length === 0 ? (
                <p className="text-sm text-text-tertiary italic">No activity yet.</p>
            ) : (
                <div className="space-y-6">
                    {activities.map(act => (
                        <div key={act.id} className="flex gap-4">
                            <div className="w-10 h-10 rounded-full bg-bg-card border border-border-subtle flex items-center justify-center font-bold text-xs text-text-tertiary shadow-sm flex-shrink-0">
                                {act.actor?.[0]?.toUpperCase() || '?'}
                            </div>
                            <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-3 mb-1">
                                    <span className="text-sm font-bold text-text-primary">{act.actor}</span>
                                    <span className="text-xs text-text-tertiary">
                                        {new Date(act.created_at).toLocaleDateString()} at {new Date(act.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                    </span>
                                </div>
                                <div className="text-sm text-text-secondary break-words">
                                    <span className="text-accent-primary font-medium mr-1">{act.action}</span>
                                    {act.detail}
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
});

// The thread re-renders only when the activity list changes, never per keystroke.
const CommentList = React.memo(function CommentList({ activities }) {
    // Comments only — the full activity timeline lives in the board side panel.
    const comments = activities.filter(a => a.action === 'commented');
    return (
        <div className="space-y-6">
            {comments.length === 0 && <p className="text-sm text-text-tertiary italic">No comments yet.</p>}
            {comments.map(act => (
                <div key={act.id} className="flex gap-4 group">
                    <div className="w-10 h-10 rounded-full bg-bg-card border border-border-subtle flex items-center justify-center font-bold text-xs text-text-tertiary shadow-sm flex-shrink-0">
                        {act.actor?.[0]?.toUpperCase() || '?'}
                    </div>
                    <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-3 mb-1">
                            <span className="text-sm font-bold text-text-primary">{act.actor}</span>
                            <span className="text-xs text-text-tertiary">
                                {new Date(act.created_at).toLocaleDateString()} at {new Date(act.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                            </span>
                        </div>
                        <div className="text-sm text-text-secondary bg-bg-card border border-border-subtle rounded-lg px-4 py-3 break-words">
                            {act.detail}
                        </div>
                    </div>
                </div>
            ))}
        </div>
    );
});

export function CommentsSection({ user, onComment, activities, projectId, members }) {
    return (
        <div>
            <h2 className="text-sm font-bold uppercase text-text-tertiary mb-4 flex items-center gap-2">
                <MessageSquare className="w-4 h-4" /> Comments
            </h2>
            <CommentComposer user={user} projectId={projectId} members={members} onSubmit={onComment} />
            <CommentList activities={activities} />
        </div>
    );
}
