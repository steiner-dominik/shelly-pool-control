"""WebSocket fan-out: the poller pushes snapshots, clients receive live state."""

from __future__ import annotations

import asyncio
import json


class WsHub:
    def __init__(self):
        self._queues: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=32)
        self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._queues.discard(q)

    def publish(self, message: dict) -> None:
        data = json.dumps(message)
        for q in list(self._queues):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                # slow client: drop oldest, keep newest
                try:
                    q.get_nowait()
                    q.put_nowait(data)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass


hub = WsHub()
