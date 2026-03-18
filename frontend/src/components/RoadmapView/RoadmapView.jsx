import React, { useState, useEffect } from 'react';
import { CalendarDays, Flag, Clock, Layers } from 'lucide-react';
import { api } from '../../api';

export function RoadmapView({ projectId }) {
    const [roadmapData, setRoadmapData] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    // Mock data for Gantt chart if API is empty or missing fields
    const mockGanttData = [
        { id: '1', title: 'Phase 1: Foundation', start: '2026-03-01', end: '2026-03-15', progress: 100, color: 'bg-blue-500' },
        { id: '2', title: 'Design System', start: '2026-03-10', end: '2026-03-25', progress: 60, color: 'bg-purple-500' },
        { id: '3', title: 'Frontend Implementation', start: '2026-03-20', end: '2026-04-10', progress: 20, color: 'bg-green-500' },
        { id: '4', title: 'Backend APIs', start: '2026-03-15', end: '2026-04-05', progress: 40, color: 'bg-orange-500' },
        { id: '5', title: 'Beta Testing', start: '2026-04-10', end: '2026-04-30', progress: 0, color: 'bg-red-500' }
    ];

    useEffect(() => {
        if (!projectId) {
            setError("Project ID is missing.");
            setLoading(false);
            return;
        }

        const fetchRoadmap = async () => {
            try {
                setLoading(true);
                setError(null);
                // Attempt to fetch, fallback to mock if API fails or returns empty
                const data = await api.getRoadmap(projectId).catch(() => []);
                setRoadmapData(data && data.length > 0 ? data : mockGanttData);
            } catch (err) {
                console.error("Failed to fetch roadmap:", err);
                setRoadmapData(mockGanttData); // Fallback to mock on hard error
            } finally {
                setLoading(false);
            }
        };

        fetchRoadmap();
    }, [projectId]);

    if (loading) {
        return (
            <div className="flex flex-col items-center justify-center h-full text-muted-foreground p-12">
                <Clock className="w-8 h-8 mb-4 animate-spin text-primary" />
                <p>Loading roadmap timeline...</p>
            </div>
        );
    }

    if (error) {
        return <div className="p-6 text-center text-red-500 bg-red-500/10 rounded-lg m-6">Error: {error}</div>;
    }

    if (roadmapData.length === 0) {
        return (
            <div className="p-12 bg-bg-panel border border-border-subtle rounded-xl shadow-sm h-full flex flex-col items-center justify-center text-text-muted">
                <CalendarDays className="mb-4 text-border-strong" size={48} />
                <p className="text-lg font-medium">No roadmap items found.</p>
                <p className="text-sm mt-2">Create epics and milestones to populate the timeline.</p>
            </div>
        );
    }

    // Generate timeline months
    const months = ['March', 'April', 'May', 'June'];

    return (
        <div className="p-6 bg-bg-panel border border-border-subtle rounded-xl shadow-sm h-full flex flex-col">
            <div className="flex items-center justify-between mb-6">
                <h3 className="text-xl font-semibold text-text-primary flex items-center gap-2">
                    <Layers className="text-primary w-5 h-5" />
                    Project Roadmap
                </h3>
                <div className="flex gap-2">
                    <button className="btn btn-ghost btn-sm">Today</button>
                    <div className="flex bg-bg-card rounded-md border border-border-subtle overflow-hidden">
                        <button className="px-3 py-1 text-sm bg-bg-hover text-text-primary">Months</button>
                        <button className="px-3 py-1 text-sm text-text-muted hover:text-text-primary">Quarters</button>
                    </div>
                </div>
            </div>

            <div className="flex-1 overflow-x-auto overflow-y-auto border border-border-subtle rounded-lg bg-bg-card">
                <div className="min-w-[800px]">
                    {/* Header: Time scale */}
                    <div className="flex border-b border-border-subtle bg-bg-panel sticky top-0 z-10">
                        <div className="w-64 p-3 border-r border-border-subtle font-medium text-text-secondary text-sm flex items-center">
                            Epic / Milestone
                        </div>
                        <div className="flex-1 flex">
                            {months.map((month, idx) => (
                                <div key={idx} className="flex-1 border-r border-border-subtle p-2 text-center text-sm font-medium text-text-secondary">
                                    {month} 2026
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Gantt Rows */}
                    <div className="relative">
                        {/* Background Grid Lines */}
                        <div className="absolute inset-0 flex pointer-events-none">
                            <div className="w-64 border-r border-border-subtle bg-bg-card"></div>
                            <div className="flex-1 flex">
                                {months.map((_, idx) => (
                                    <div key={idx} className="flex-1 border-r border-border-subtle opacity-30"></div>
                                ))}
                            </div>
                        </div>

                        {/* Data Rows */}
                        <div className="relative z-0">
                            {roadmapData.map((item, index) => {
                                const viewStart = new Date('2026-03-01').getTime();
                                const viewEnd = new Date('2026-06-30').getTime();
                                const duration = viewEnd - viewStart;
                                const tStart = new Date(item.start || '2026-03-01').getTime();
                                const tEnd = new Date(item.end || '2026-03-15').getTime();
                                const clampStart = Math.max(tStart, viewStart);
                                const clampEnd = Math.min(tEnd, viewEnd);
                                const startPos = ((clampStart - viewStart) / duration) * 100;
                                const widthPos = Math.max(((clampEnd - clampStart) / duration) * 100, 2);

                                return (
                                    <div key={item.id} className="flex border-b border-border-subtle hover:bg-bg-hover/50 transition-colors group">
                                        <div className="w-64 p-3 border-r border-border-subtle flex items-center gap-2 z-10 bg-bg-card group-hover:bg-transparent">
                                            <Flag className={`w-4 h-4 ${item.color ? item.color.replace('bg-', 'text-') : 'text-primary'}`} />
                                            <span className="text-sm font-medium text-text-primary truncate" title={item.title}>{item.title}</span>
                                        </div>
                                        <div className="flex-1 relative p-2 flex items-center">
                                            {/* Gantt Bar */}
                                            <div 
                                                className={`absolute h-8 rounded-md shadow-sm ${item.color || 'bg-primary'} flex items-center overflow-hidden cursor-pointer hover:opacity-90 transition-opacity`}
                                                style={{ left: `${startPos}%`, width: `${widthPos}%` }}
                                                title={`${item.title} (${item.progress || 0}% complete)`}
                                            >
                                                {/* Progress fill inside bar */}
                                                {item.progress !== undefined && (
                                                    <div 
                                                        className="absolute top-0 left-0 bottom-0 bg-black/20" 
                                                        style={{ width: `${item.progress}%` }}
                                                    ></div>
                                                )}
                                                <span className="relative z-10 px-2 text-xs font-medium text-white truncate drop-shadow-sm">
                                                    {item.progress !== undefined ? `${item.progress}%` : ''}
                                                </span>
                                            </div>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}

