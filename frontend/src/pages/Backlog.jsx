import React, { useState, useEffect } from 'react';
import { Layout } from '../components/Layout';
import { api } from '../api';
import { TaskCard } from '../components/TaskCard';
import { TaskDetailPanel } from '../components/TaskDetailPanel';
import { CreateTaskModal } from '../components/CreateTaskModal';
import { PlusCircle } from 'lucide-react';

export function Backlog() {
    const [tasks, setTasks] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [filterStatus, setFilterStatus] = useState('');
    const [filterAssignee, setFilterAssignee] = useState('');
    const [filterPriority, setFilterPriority] = useState('');
    const [sortKey, setSortKey] = useState('created_at');
    const [sortDirection, setSortDirection] = useState('desc');
    const [selectedTask, setSelectedTask] = useState(null);
    const [isCreateTaskModalOpen, setIsCreateTaskModalOpen] = useState(false);

    const fetchTasks = async () => {
        setLoading(true);
        setError(null);
        try {
            const fetchedTasks = await api.listTasks(
                undefined, // projectId (not filtering by project ID for now)
                filterStatus || undefined,
                filterAssignee || undefined,
                filterPriority || undefined
            );

            // Client-side sorting
            const sortedTasks = [...fetchedTasks].sort((a, b) => {
                let valA = a[sortKey];
                let valB = b[sortKey];

                if (sortKey === 'priority') {
                    const priorityOrder = { 'critical': 4, 'high': 3, 'medium': 2, 'low': 1 };
                    valA = priorityOrder[a.priority.toLowerCase()] || 0;
                    valB = priorityOrder[b.priority.toLowerCase()] || 0;
                }

                if (valA < valB) return sortDirection === 'asc' ? -1 : 1;
                if (valA > valB) return sortDirection === 'asc' ? 1 : -1;
                return 0;
            });

            setTasks(sortedTasks);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchTasks();
    }, [filterStatus, filterAssignee, filterPriority, sortKey, sortDirection]);

    const handleTaskClick = (task) => {
        setSelectedTask(task);
    };

    const handleCloseTaskDetail = () => {
        setSelectedTask(null);
    };

    const handleTaskCreated = () => {
        setIsCreateTaskModalOpen(false);
        fetchTasks(); // Refresh tasks after creation
    };

    return (
        <Layout>
            <div className="flex-1 p-4 md:p-6 space-y-4 md:space-y-6 overflow-x-hidden">
                <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-4 md:mb-6">
                    <h1 className="text-2xl md:text-3xl font-bold text-primary">Backlog</h1>
                    <button
                        onClick={() => setIsCreateTaskModalOpen(true)}
                        className="flex items-center justify-center w-full sm:w-auto px-4 py-2 bg-blue-600 text-white rounded-md shadow-md hover:bg-blue-700 transition-colors"
                    >
                        <PlusCircle className="mr-2 h-5 w-5" />
                        New Task
                    </button>
                </div>

                {/* Filters and Sorting */}
                <div className="bg-card p-4 rounded-lg shadow-sm flex flex-col sm:flex-row flex-wrap gap-4 items-stretch sm:items-center">
                    <select
                        value={filterStatus}
                        onChange={(e) => setFilterStatus(e.target.value)}
                        className="p-2 border border-border rounded-md bg-input text-input-foreground w-full sm:w-auto"
                    >
                        <option value="">All Statuses</option>
                        <option value="backlog">Backlog</option>
                        <option value="todo">To Do</option>
                        <option value="in_progress">In Progress</option>
                        <option value="review">Review</option>
                        <option value="done">Done</option>
                    </select>

                    <input
                        type="text"
                        placeholder="Filter by Assignee"
                        value={filterAssignee}
                        onChange={(e) => setFilterAssignee(e.target.value)}
                        className="p-2 border border-border rounded-md bg-input text-input-foreground w-full sm:w-auto"
                    />

                    <select
                        value={filterPriority}
                        onChange={(e) => setFilterPriority(e.target.value)}
                        className="p-2 border border-border rounded-md bg-input text-input-foreground w-full sm:w-auto"
                    >
                        <option value="">All Priorities</option>
                        <option value="low">Low</option>
                        <option value="medium">Medium</option>
                        <option value="high">High</option>
                        <option value="critical">Critical</option>
                    </select>

                    <select
                        value={sortKey}
                        onChange={(e) => setSortKey(e.target.value)}
                        className="p-2 border border-border rounded-md bg-input text-input-foreground w-full sm:w-auto"
                    >
                        <option value="created_at">Sort by Created Date</option>
                        <option value="priority">Sort by Priority</option>
                        <option value="title">Sort by Title</option>
                    </select>

                    <select
                        value={sortDirection}
                        onChange={(e) => setSortDirection(e.target.value)}
                        className="p-2 border border-border rounded-md bg-input text-input-foreground w-full sm:w-auto"
                    >
                        <option value="desc">Descending</option>
                        <option value="asc">Ascending</option>
                    </select>
                </div>

                {loading && <p className="text-center text-secondary">Loading tasks...</p>}
                {error && <p className="text-center text-red-500">Error: {error}</p>}

                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
                    {!loading && tasks.length === 0 && <p className="col-span-full text-center text-secondary">No tasks found.</p>}
                    {tasks.map((task) => (
                        <TaskCard key={task.id} task={task} onClick={() => handleTaskClick(task)} />
                    ))}
                </div>
            </div>

            {selectedTask && (
                <TaskDetailPanel task={selectedTask} onClose={handleCloseTaskDetail} onUpdate={fetchTasks} />
            )}

            <CreateTaskModal
                isOpen={isCreateTaskModalOpen}
                onClose={() => setIsCreateTaskModalOpen(false)}
                onTaskCreated={handleTaskCreated}
            />
        </Layout>
    );
}
