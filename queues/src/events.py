"""Fan-out of change events to the live stream of each room.

publish runs in a worker thread, so it hands the event to the loop with
call_soon_threadsafe. subscribe runs inside the SSE generator.
"""

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class _Subscriber:
    """One open SSE connection: its queue and the loop that reads it."""

    queue: asyncio.Queue[dict]
    loop: asyncio.AbstractEventLoop


class Broadcaster:
    """Pub/sub of small event dicts, one subscriber per open connection."""

    def __init__(self) -> None:
        self._subs: dict[int, set[_Subscriber]] = {}

    def subscribe(self, room_id: int) -> asyncio.Queue[dict]:
        """Registers a subscriber on the running loop and returns its queue."""
        sub = _Subscriber(queue=asyncio.Queue(), loop=asyncio.get_running_loop())
        self._subs.setdefault(room_id, set()).add(sub)
        return sub.queue

    def publish(self, room_id: int, event: dict) -> None:
        """Pushes event to every subscriber of room_id, from any thread."""
        for sub in self._subs.get(room_id, ()):
            sub.loop.call_soon_threadsafe(sub.queue.put_nowait, event)

    def unsubscribe(self, room_id: int, queue: asyncio.Queue[dict]) -> None:
        """Drops the subscriber that owns queue."""
        subs = self._subs.get(room_id, set())
        for sub in list(subs):
            if sub.queue is queue:
                subs.discard(sub)


events = Broadcaster()
