"""In-memory notification signaling logic."""

import asyncio
from typing import Dict, Set

class NotificationBroker:
    """Thread-safe in-memory signaling for notifications."""
    def __init__(self):
        self._listeners: Dict[str, Set[asyncio.Event]] = {}

    def subscribe(self, profile_id: str) -> asyncio.Event:
        """Subscribe to notifications for a user."""
        event = asyncio.Event()
        if profile_id not in self._listeners:
            self._listeners[profile_id] = set()
        self._listeners[profile_id].add(event)
        return event

    def unsubscribe(self, profile_id: str, event: asyncio.Event):
        """Unsubscribe."""
        if profile_id in self._listeners:
            self._listeners[profile_id].discard(event)
            if not self._listeners[profile_id]:
                del self._listeners[profile_id]

    def notify(self, profile_id: str):
        """Wake up all listeners for a user. Thread-safe."""
        if profile_id in self._listeners:
            for event in self._listeners[profile_id]:
                try:
                    # Thread-safe set for async events running in another loop
                    loop = event._loop
                    if not loop.is_closed():
                        loop.call_soon_threadsafe(event.set)
                except Exception:
                    pass

# Singleton instance
broker = NotificationBroker()
