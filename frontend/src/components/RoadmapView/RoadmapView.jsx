import React, { useState, useEffect } from 'react';
import { Lightbulb, CalendarDays, FlagCheckered } from 'lucide-react'; // Example icons for milestones
import { api } from '../../api'; // Import the API client

export function RoadmapView({ projectId }) { // Assume projectId is passed as a prop
    const [roadmapData, setRoadmapData] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

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
                const data = await api.getRoadmap(projectId);
                setRoadmapData(data);
            } catch (err) {
                console.error("Failed to fetch roadmap:", err);
                setError("Failed to load roadmap data.");
            } finally {
                setLoading(false);
            }
        };

        fetchRoadmap();
    }, [projectId]); // Re-run effect if projectId changes

    if (loading) {
        return <div className="p-6 text-center text-muted-foreground">Loading roadmap...</div>;
    }

    if (error) {
        return <div className="p-6 text-center text-red-500">Error: {error}</div>;
    }

    if (roadmapData.length === 0) {
        return (
            <div className="p-6 bg-card rounded-lg shadow-md h-full flex flex-col items-center justify-center text-muted-foreground">
                <CalendarDays className="mb-4" size={48} />
                <p className="text-lg">No roadmap items found for this project.</p>
                <p className="text-sm mt-2">Start by adding new milestones or phases.</p>
            </div>
        );
    }

    return (
        <div className="p-4 md:p-6 bg-card rounded-lg shadow-md h-full overflow-y-auto overflow-x-hidden">
            <h3 className="text-lg md:text-xl font-semibold text-primary mb-4 flex items-center">
                <CalendarDays className="mr-2 text-muted-foreground" size={20} />
                Project Roadmap
            </h3>
            <div className="relative border-l-2 border-border pl-4 md:pl-6 ml-2 md:ml-0">
                {roadmapData.map((item) => (
                    <div key={item.id} className="mb-6 md:mb-8">
                        <div className="absolute -left-[17px] md:-left-[21px] mt-1 w-5 h-5 md:w-6 md:h-6 bg-accent rounded-full flex items-center justify-center">
                            {/* Dynamically choose icon based on item.icon or default. Assuming 'item.icon' provides a string that maps to Lucide icons. */}
                            {/* For now, just using Lightbulb as a placeholder */}
                            <Lightbulb className="text-accent-foreground w-3 h-3 md:w-4 md:h-4" />
                        </div>
                        <p className="text-xs md:text-sm text-muted-foreground">{item.quarter || 'N/A'}</p>
                        <h4 className="font-medium text-base md:text-lg lg:text-xl text-foreground break-words">{item.title}</h4>
                        <p className="text-xs md:text-sm lg:text-base text-secondary-foreground mt-1 break-words">
                            {item.description}
                        </p>
                    </div>
                ))}
            </div>
        </div>
    );
}

