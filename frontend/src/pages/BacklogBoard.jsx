import React from 'react';
import { Layout } from '../components/Layout'; // Assuming a common layout component

const BacklogBoard = () => {
  return (
    <Layout>
      <div className="flex-1 p-6 bg-gray-100 dark:bg-gray-900 min-h-screen">
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-6">Product Backlog</h1>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {/* Placeholder for Backlog Items/Task Cards */}
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4">
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">Backlog Item 1</h2>
            <p className="text-gray-600 dark:text-gray-300">Description for backlog item 1.</p>
            <span className="inline-block bg-blue-100 text-blue-800 text-xs font-medium px-2.5 py-0.5 rounded-full dark:bg-blue-900 dark:text-blue-300 mt-3">Medium Priority</span>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4">
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">Backlog Item 2</h2>
            <p className="text-gray-600 dark:text-gray-300">Description for backlog item 2.</p>
            <span className="inline-block bg-green-100 text-green-800 text-xs font-medium px-2.5 py-0.5 rounded-full dark:bg-green-900 dark:text-green-300 mt-3">Low Priority</span>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4">
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">Backlog Item 3</h2>
            <p className="text-gray-600 dark:text-gray-300">Description for backlog item 3.</p>
            <span className="inline-block bg-red-100 text-red-800 text-xs font-medium px-2.5 py-0.5 rounded-full dark:bg-red-900 dark:text-red-300 mt-3">High Priority</span>
          </div>
        </div>
      </div>
    </Layout>
  );
};

export default BacklogBoard;
