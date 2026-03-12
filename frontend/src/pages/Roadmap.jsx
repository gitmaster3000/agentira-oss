import React from 'react';
import { Layout } from '../components/Layout';
import { RoadmapView } from '../components/RoadmapView/RoadmapView';

export function Roadmap() {
    // In a real application, projectId would likely come from URL params (e.g., /project/:projectId/roadmap)
    // or from a global context if a project is selected.
    // For now, using a placeholder project ID for demonstration.
    const projectId = "7b4232d3e521"; // Using the project ID from the webhook event

    return (
        <Layout>
            <div className="flex-1 p-6">
                <RoadmapView projectId={projectId} />
            </div>
        </Layout>
    );
}
