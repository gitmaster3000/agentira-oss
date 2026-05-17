import React from 'react';
import { useParams } from 'react-router-dom';
import { Layout } from '../components/Layout';
import { RoadmapView } from '../components/RoadmapView/RoadmapView';

export function Roadmap() {
    const { projectId } = useParams();

    return (
        <Layout>
            <div className="flex-1 p-6">
                <RoadmapView projectId={projectId} />
            </div>
        </Layout>
    );
}
