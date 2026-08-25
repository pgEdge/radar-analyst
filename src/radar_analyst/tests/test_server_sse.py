"""Tests for the in-process SSE pub/sub hub."""

import asyncio
from uuid import uuid4

from radar_analyst.server.sse import SSEHub


async def test_subscriber_receives_published_event() -> None:
    hub = SSEHub()
    job_id = uuid4()
    received: list[dict[str, object]] = []

    async def consume() -> None:
        async with hub.subscribe(job_id) as sub:
            async for ev in sub.events():
                received.append(ev)

    task = asyncio.create_task(consume())
    # Wait one tick so the subscriber has registered.
    await asyncio.sleep(0.01)
    hub.publish(
        job_id, {"type": "phase", "phase": "parsing"}
    )
    hub.publish(job_id, {"type": "done"})
    await asyncio.wait_for(task, timeout=1.0)
    assert received == [
        {"type": "phase", "phase": "parsing"},
        {"type": "done"},
    ]


async def test_multiple_subscribers_all_receive() -> None:
    hub = SSEHub()
    job_id = uuid4()
    out_a: list[dict[str, object]] = []
    out_b: list[dict[str, object]] = []

    async def consume(
        out: list[dict[str, object]],
    ) -> None:
        async with hub.subscribe(job_id) as sub:
            async for ev in sub.events():
                out.append(ev)

    t_a = asyncio.create_task(consume(out_a))
    t_b = asyncio.create_task(consume(out_b))
    await asyncio.sleep(0.01)
    hub.publish(job_id, {"type": "phase", "phase": "ruling"})
    hub.publish(job_id, {"type": "done"})
    await asyncio.wait_for(
        asyncio.gather(t_a, t_b), timeout=1.0
    )
    assert out_a == out_b
    assert len(out_a) == 2


async def test_publish_with_no_subscribers_is_noop() -> None:
    hub = SSEHub()
    # Must not raise, must not grow an orphan queue.
    hub.publish(uuid4(), {"type": "phase"})
    assert hub._queues == {}  # noqa: SLF001


async def test_subscriber_cleans_up_on_exit() -> None:
    hub = SSEHub()
    job_id = uuid4()

    async def consume() -> None:
        async with hub.subscribe(job_id) as sub:
            async for ev in sub.events():
                if ev["type"] == "done":
                    return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    hub.publish(job_id, {"type": "done"})
    await asyncio.wait_for(task, timeout=1.0)
    # After the subscriber has exited, the hub must not be holding a
    # stale queue for the job.
    assert job_id not in hub._queues  # noqa: SLF001


async def test_error_event_is_also_terminal() -> None:
    hub = SSEHub()
    job_id = uuid4()
    received: list[dict[str, object]] = []

    async def consume() -> None:
        async with hub.subscribe(job_id) as sub:
            async for ev in sub.events():
                received.append(ev)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    hub.publish(
        job_id, {"type": "error", "message": "oops"}
    )
    await asyncio.wait_for(task, timeout=1.0)
    assert received == [
        {"type": "error", "message": "oops"},
    ]
