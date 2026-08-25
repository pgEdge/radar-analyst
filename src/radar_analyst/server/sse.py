"""In-process SSE pub/sub hub.

One :class:`asyncio.Queue` per subscriber. The orchestrator publishes
events; the SSE endpoint subscribes for the duration of a client's
connection. Terminal events (``done`` / ``error``) close the subscriber
iterator so clients disconnect cleanly.

Scoped to a single process: every publisher and subscriber must
live in the one uvicorn worker the analyst runs as, which is why an
in-memory hub is sufficient.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

_TERMINAL_EVENTS: frozenset[str] = frozenset({"done", "error"})


class SSEHub:
    """In-process pub/sub for job progress events."""
    def __init__(self) -> None:
        self._queues: dict[
            UUID, list[asyncio.Queue[dict[str, Any]]]
        ] = defaultdict(list)

    def publish(self, job_id: UUID, event: dict[str, Any]) -> None:
        """Deliver *event* to all current subscribers of *job_id*."""
        queues = self._queues.get(job_id)
        if not queues:
            return
        # Copy the list: a subscriber might unsubscribe mid-iteration
        # if its consumer sees a terminal event and exits.
        for q in list(queues):
            q.put_nowait(event)

    def subscribe(self, job_id: UUID) -> SSESubscription:
        """A subscription context for *job_id*."""
        return SSESubscription(self, job_id)


class SSESubscription:
    """One subscriber's queue, scoped to a job."""
    def __init__(self, hub: SSEHub, job_id: UUID) -> None:
        self._hub = hub
        self._job_id = job_id
        self._queue: asyncio.Queue[dict[str, Any]] = (
            asyncio.Queue()
        )

    async def __aenter__(self) -> SSESubscription:
        self._hub._queues[self._job_id].append(self._queue)
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        tb: object,
    ) -> None:
        queues = self._hub._queues.get(self._job_id)
        if queues is not None and self._queue in queues:
            queues.remove(self._queue)
        if queues is not None and not queues:
            self._hub._queues.pop(self._job_id, None)

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        """Yield events until a terminal one arrives."""
        while True:
            event = await self._queue.get()
            yield event
            if event.get("type") in _TERMINAL_EVENTS:
                return
