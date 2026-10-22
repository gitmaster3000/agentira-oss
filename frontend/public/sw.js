// Web Push receiver: shows the notification and opens the linked page on tap.
self.addEventListener('push', (e) => {
    const d = e.data ? e.data.json() : {};
    e.waitUntil(self.registration.showNotification(d.title || 'Agentira', {
        body: d.body || '', data: { url: d.url || '/' }, icon: '/favicon.svg',
    }));
});
self.addEventListener('notificationclick', (e) => {
    e.notification.close();
    e.waitUntil(self.clients.openWindow(e.notification.data.url));
});
